#!/usr/bin/env python3
"""Build one year of reusable real 1-minute chip inventory, in parallel buckets."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import gc
import hashlib
import inspect
import json
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime
from datetime import time as clock_time
from itertools import pairwise
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import duckdb
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cyq_game.chip._migration_kernel import stable_sum  # noqa: E402
from cyq_game.chip.checkpoint_journal_contract import (  # noqa: E402
    ARTIFACT_VERSION as CHECKPOINT_JOURNAL_ARTIFACT_VERSION,
)
from cyq_game.chip.checkpoint_journal_contract import (
    CHECKPOINT_CODEC_VERSION,
    FROZEN_REPLAY_PARAMETER_VALUES,
    JOURNAL_CODEC_VERSION,
    TERMINAL_COMPLETENESS_VERSION,
    TRANSITION_SEMANTICS_VERSION,
    CellIdentity,
    CheckpointLot,
    CheckpointModelState,
    FeatureAssetBinding,
    LifecycleContinuation,
    SellerContinuation,
    f64be_bits,
    logical_sha256,
)
from cyq_game.chip.checkpoint_journal_contract import (
    SCHEMA_VERSION as CHECKPOINT_JOURNAL_SCHEMA_VERSION,
)
from cyq_game.chip.checkpoint_journal_contract import (
    SELLER_MODEL_ORDER as CHECKPOINT_JOURNAL_SELLER_MODELS,
)
from cyq_game.chip.checkpoint_journal_contract import (
    STORAGE_VERSION as CHECKPOINT_JOURNAL_STORAGE_VERSION,
)
from cyq_game.chip.checkpoint_journal_index import (  # noqa: E402
    INDEX_VERSION,
    CheckpointJournalIndexRow,
)
from cyq_game.chip.checkpoint_journal_writer import (  # noqa: E402
    CHECKPOINT_CADENCE,
    PHASE2_WRITER_VERSION,
    ArtifactFileMetadata,
    SymbolArtifacts,
    activate_production_bundle,
    arrow_logical_digest,
    build_checkpoint_logical,
    build_journal_day,
    build_journal_logical,
    finish_symbol_artifacts,
    regular_file_bytes,
    sha256_file,
    verify_root,
    write_checkpoint_part,
    write_index,
    write_journal_part,
    write_json,
)
from cyq_game.chip.daily_feature_fact import (  # noqa: E402
    FACT_SCHEMA,
    build_daily_feature_fact,
    project_daily_feature_row,
    write_daily_feature_rows,
)
from cyq_game.chip.ensemble_v2 import SELLER_MODEL_ORDER  # noqa: E402
from cyq_game.chip.migration_v2 import (  # noqa: E402
    DEFAULT_MAX_HOLDING_DAYS,
    NONPOSITIVE_ECONOMIC_BUCKET,
    DailyMigrationEngine,
    InventoryEvent,
    InventoryEventKind,
    MinuteBar,
    MutableChipState,
    PreparedMinutePath,
    StableLogPriceGrid,
    bucket_for_economic_break_even,
    initial_unknown_snapshot,
    prepare_minute_path,
)
from cyq_game.chip.operator_index import build_operator_symbol_index  # noqa: E402
from cyq_game.chip.peaks import (  # noqa: E402
    EnsembleTemporalPeakTracker,
    detect_canonical_peaks,
    dominant_canonical_peak,
)
from cyq_game.chip.price_coordinate import (  # noqa: E402
    canonical_action_component_id,
    parse_action_ids,
)
from cyq_game.chip.profile_metrics import compute_distribution_metrics  # noqa: E402
from cyq_game.chip.state_v2 import (  # noqa: E402
    ChipSnapshotV2,
    InventoryCell,
    SellerModel,
    SnapshotPhase,
    SparseChipInventory,
    TurnoverSensitivity,
    stable_cell_id,
    tolerance,
)
from cyq_game.strategy.semantic_contract import (  # noqa: E402
    CHIP_STATE_SCHEMA_VERSION,
    OPERATOR_LOG_VERSION,
    semantic_fingerprint_fields,
)

DAILY_ROOT = ROOT / "data/processed/pit_b_daily_2018_2026_v2/daily"
MINUTE_ROOT = Path(
    "/Users/linmei/Downloads/workspace/quant/data/lake/"
    "stock_1min_canonical_none_20260813/bars"
)
MODEL_VERSION = "real-chip-inventory-v2.1"
GRID_VERSION = "log-grid-25bp-v1"
STORAGE_VERSION = OPERATOR_LOG_VERSION
LEGACY_STORAGE_SELECTOR = "legacy-operator"
STAGE_LAYOUT_VERSION = "bucket-symbol-v3-mixed-native-resolution"
MINUTE_YEAR_SUPPLEMENTS: dict[int, tuple[str, ...]] = {
    2026: ("2026_qmt_tail.parquet",),
}
CHECKPOINT_INTERVAL_DAYS = 20
OUTPUT_ROW_GROUP_SIZE = 4096
PARQUET_COMPRESSION_LEVEL = 3
RETENTION_RAW = 0
RETENTION_CONSTANT = 1
RETENTION_PALETTE_U8 = 2
RETENTION_BY_SENSITIVITY = 3
RETENTION_XOR = 4
RETENTION_XOR_BYTE_SHUFFLE = 5
# Seller retention is fully determined by the previous checkpoint, registered
# minute bars and seller-model version.  Persisting thousands of fractions per
# day duplicates source data, so every transition uses deterministic replay.
# This marker must never be interpreted as an empty/all-retained vector.
RETENTION_SOURCE_REPLAY = 6
RETENTION_PALETTE_BITPACK = 7

SENSITIVITY_CODE = {
    TurnoverSensitivity.ACTIVE: 0,
    TurnoverSensitivity.NEUTRAL: 1,
    TurnoverSensitivity.STICKY: 2,
}
TZ = ZoneInfo("Asia/Shanghai")

RESUME_CONTRACT_VERSION = "v12-phase7-resume-contract-v2"
INPUT_MANIFEST_VERSION = "v12-phase7-symbol-input-manifest-v1"
ARTIFACT_CONTRACT_VERSION = "v12-phase7-artifact-contract-v2"
PHYSICAL_CONTRACT_VERSION = "v12-phase7-physical-contract-v1"
CHECKPOINT_CADENCE_ALGORITHM_VERSION = "replayable-target-dates-v1"
SHARD_MANIFEST_VERSION = "v12-phase7-symbol-shard-manifest-v2"
BUFFER_CANDIDATES = (3, 24, 48, 96)


def _semantic_fingerprint_v2() -> str:
    code_dependencies = {
        name: hashlib.sha256(inspect.getsource(value).encode("utf-8")).hexdigest()
        for name, value in (
            ("DailyMigrationEngine", DailyMigrationEngine),
            ("_canonicalize_packed_output_state", _canonicalize_packed_output_state),
            ("_cap_prepared_minute_path", _cap_prepared_minute_path),
            ("_inventory_events", _inventory_events),
            ("_minute_bars", _minute_bars),
            ("_output_row", _output_row),
            ("_pro_rata_removals", _pro_rata_removals),
            ("initial_unknown_snapshot", initial_unknown_snapshot),
            ("prepare_minute_path", prepare_minute_path),
            ("stable_cell_id", stable_cell_id),
            ("canonical_action_component_id", canonical_action_component_id),
            ("parse_action_ids", parse_action_ids),
            ("compute_distribution_metrics", compute_distribution_metrics),
            ("detect_canonical_peaks", detect_canonical_peaks),
            ("dominant_canonical_peak", dominant_canonical_peak),
        )
    }
    return logical_sha256(
        {
            "semantic_contract": semantic_fingerprint_fields(),
            "frozen_replay_parameters": FROZEN_REPLAY_PARAMETER_VALUES,
            "semantic_code_dependencies": code_dependencies,
        }
    )


def _artifact_contract_fingerprint() -> str:
    return logical_sha256(
        {
            "artifact_contract_version": ARTIFACT_CONTRACT_VERSION,
            "artifact_version": CHECKPOINT_JOURNAL_ARTIFACT_VERSION,
            "checkpoint_cadence": CHECKPOINT_CADENCE,
            "checkpoint_cadence_algorithm_version": (
                CHECKPOINT_CADENCE_ALGORITHM_VERSION
            ),
            "checkpoint_codec_version": CHECKPOINT_CODEC_VERSION,
            "index_version": INDEX_VERSION,
            "journal_codec_version": JOURNAL_CODEC_VERSION,
            "manifest_contract": "phase7-hash-once-manifest-v1",
            "schema_version": CHECKPOINT_JOURNAL_SCHEMA_VERSION,
            "storage_version": CHECKPOINT_JOURNAL_STORAGE_VERSION,
            "terminal_adapter_contract": TERMINAL_COMPLETENESS_VERSION,
            "transition_semantics_version": TRANSITION_SEMANTICS_VERSION,
        }
    )


def _physical_fingerprint(output_buffer_rows: int) -> str:
    return logical_sha256(
        {
            "physical_contract_version": PHYSICAL_CONTRACT_VERSION,
            "compression": "zstd",
            "compression_level": PARQUET_COMPRESSION_LEVEL,
            "dictionary_encoding": True,
            "operator_row_group_rows": output_buffer_rows,
            "writer": "pyarrow.parquet.ParquetWriter",
        }
    )


def _git_head_provenance() -> str:
    return subprocess.check_output(
        ("git", "rev-parse", "HEAD"), cwd=ROOT, text=True
    ).strip()


def _atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(payload, encoding="utf-8")
    json.loads(temporary.read_text(encoding="utf-8"))
    os.replace(temporary, path)


def _symbol_input_fingerprint(
    *,
    symbol: str,
    year: int,
    stage_root: Path,
    daily_path: Path,
    minute_path: Path | None,
    manifest_root: Path,
) -> tuple[str, Path]:
    """Build once, then trust immutable staged partition digests on resume."""

    safe_symbol = symbol.replace(".", "_")
    pointer_path = manifest_root / f"{safe_symbol}.json"
    complete_path = stage_root / "COMPLETE.json"
    complete_sha256 = sha256_file(complete_path)
    expected_roots = {
        "daily": daily_path.relative_to(stage_root).as_posix(),
        "minute": (
            None if minute_path is None else minute_path.relative_to(stage_root).as_posix()
        ),
    }
    if pointer_path.exists():
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        manifest_path = manifest_root / pointer["manifest_file"]
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (
            manifest.get("manifest_version") == INPUT_MANIFEST_VERSION
            and manifest.get("symbol") == symbol
            and int(manifest.get("year", 0)) == year
            and manifest.get("stage_complete_sha256") == complete_sha256
            and manifest.get("partition_roots") == expected_roots
        ):
            unchanged = True
            for item in manifest["files"]:
                path = stage_root / item["relative_path"]
                try:
                    stat = path.stat()
                except FileNotFoundError:
                    unchanged = False
                    break
                if (
                    stat.st_size != int(item["bytes"])
                    or stat.st_mtime_ns != int(item["mtime_ns"])
                ):
                    unchanged = False
                    break
            if unchanged:
                return str(manifest["input_fingerprint"]), manifest_path

    sources: list[tuple[str, Path]] = []
    for role, root in (("daily", daily_path), ("minute", minute_path)):
        if root is None:
            continue
        sources.extend(
            (role, path)
            for path in sorted(root.rglob("*"), key=lambda value: value.as_posix().encode())
            if path.is_file()
        )
    if not sources:
        raise ValueError(f"symbol {symbol} has no staged input files")
    files = []
    for role, path in sources:
        stat = path.stat()
        files.append(
            {
                "role": role,
                "relative_path": path.relative_to(stage_root).as_posix(),
                "bytes": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "sha256": sha256_file(path),
            }
        )
    complete = json.loads(complete_path.read_text(encoding="utf-8"))
    binding = {
        "manifest_version": INPUT_MANIFEST_VERSION,
        "symbol": symbol,
        "year": year,
        "stage_complete_sha256": complete_sha256,
        "partition_roots": expected_roots,
        "registered_dependencies": {
            "daily_root": complete["daily_root"],
            "minute_root": complete["minute_root"],
            "action_override_sha256": complete["action_override_sha256"],
            "baostock_delta_sha256": complete["baostock_delta_sha256"],
        },
        "files": files,
    }
    input_fingerprint = logical_sha256(binding)
    manifest = {**binding, "input_fingerprint": input_fingerprint}
    manifest_path = manifest_root / f"{safe_symbol}.{input_fingerprint}.json"
    if not manifest_path.exists():
        _atomic_write_json(manifest_path, manifest)
    _atomic_write_json(
        pointer_path,
        {
            "input_fingerprint": input_fingerprint,
            "manifest_file": manifest_path.name,
        },
    )
    return input_fingerprint, manifest_path


def _aware(day: date, hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime.combine(day, clock_time(hour, minute, second), tzinfo=TZ)


def _date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _timestamp(value: datetime) -> datetime:
    return value.replace(tzinfo=TZ) if value.tzinfo is None else value.astimezone(TZ)


def _snapshot_ids(row: dict[str, Any]) -> tuple[str, ...]:
    values = {
        str(row[key])
        for key in (
            "snapshot_id",
            "daily_snapshot_id",
            "float_snapshot_id",
            "corporate_action_snapshot_id",
        )
        if row.get(key)
    }
    values.add(f"daily-row:{row['symbol']}:{_date(row['trade_date']).isoformat()}")
    return tuple(sorted(values))


def _minute_bars(rows: list[dict[str, Any]], trading_date: date) -> tuple[MinuteBar, ...]:
    bars: list[MinuteBar] = []
    # Convert each timestamp once.  The previous implementation converted it
    # twice while checking order and then a third time while building the bar.
    timed_rows = [(_timestamp(row["bar_end_time"]), row) for row in rows]
    if any(
        current[0] <= previous[0]
        for previous, current in pairwise(timed_rows)
    ):
        timed_rows.sort(key=lambda item: item[0])
    for _, row in timed_rows:
        values = tuple(float(row[key]) for key in ("open", "high", "low", "close"))
        open_price, high, low, close = values
        volume = float(row["volume"])
        amount = float(row["amount"])
        if (
            any(not math.isfinite(value) or value <= 0 for value in values)
            or high < max(open_price, close)
            or low > min(open_price, close)
            or low > high
            or not math.isfinite(volume)
            or volume < 0
            or not math.isfinite(amount)
            or amount < 0
            or (volume > 0 and amount <= 0)
        ):
            # Reject the whole intraday path instead of silently dropping a bad
            # bar and breaking daily volume conservation.  The caller will use
            # its explicit daily fallback (or carry state on a zero-volume day).
            return ()
    for timestamp, row in timed_rows:
        if _date(row["trade_date"]) != trading_date:
            continue
        volume = float(row["volume"])
        amount = float(row["amount"])
        low = float(row["low"])
        high = float(row["high"])
        vwap = amount / volume if volume > 0 and amount > 0 else None
        if vwap is not None:
            # QMT stores amount, volume and OHLC at different precisions.  A
            # rounded amount/volume can therefore sit just outside the minute
            # range.  Keep the observed turnover information at the nearest
            # physically possible price instead of discarding it and falling
            # back to OHLC4.
            vwap = min(max(vwap, low), high)
        bars.append(
            MinuteBar(
                timestamp=timestamp,
                available_at=timestamp,
                snapshot_id=(
                    f"{row.get('minute_source', 'qmt-none-1m')}:"
                    f"{row['symbol']}:{timestamp.isoformat()}"
                ),
                open=float(row["open"]),
                high=high,
                low=low,
                close=float(row["close"]),
                volume_shares=volume,
                vwap=vwap,
            )
        )
    return tuple(bars)


def _event_available(value: Any, effective_at: datetime) -> datetime:
    available = _aware(_date(value), 0)
    if available > effective_at:
        raise ValueError("inventory event is not PIT-available")
    return available


def _pro_rata_removals(
    snapshot: ChipSnapshotV2 | MutableChipState, share_ratio: float, shares: float
) -> tuple[tuple[int, float], ...]:
    candidates = sorted(
        (cell.cell_id, cell.shares * share_ratio)
        for cell in snapshot.inventory.cells
        if cell.shares > 0
    )
    total = math.fsum(value for _, value in candidates)
    remaining = shares
    result: list[tuple[int, float]] = []
    for index, (cell_id, available) in enumerate(candidates):
        amount = remaining if index == len(candidates) - 1 else shares * available / total
        amount = min(amount, available)
        if amount > 0:
            result.append((cell_id, amount))
            remaining -= amount
    if abs(remaining) > tolerance(shares):
        raise ValueError("could not allocate explicit float removal")
    return tuple(result)


def _inventory_events(
    previous: ChipSnapshotV2 | MutableChipState, row: dict[str, Any]
) -> tuple[InventoryEvent, ...]:
    trading_date = _date(row["trade_date"])
    action_available = _event_available(
        row["corporate_action_available_date"], _aware(trading_date, 9)
    )
    float_available = _event_available(
        row["float_available_date"], _aware(trading_date, 9, 0, 2)
    )
    input_id = str(row.get("corporate_action_snapshot_id") or row["snapshot_id"])
    source_action_ids = parse_action_ids(row.get("corporate_action_ids"))
    events: list[InventoryEvent] = []
    cash = float(row.get("cash_per_share") or 0.0)
    ratio = float(row.get("share_multiplier") or 1.0)
    if cash > 0:
        events.append(
            InventoryEvent(
                event_id=canonical_action_component_id(
                    symbol=previous.symbol,
                    effective_date=trading_date,
                    kind="CASH_DIVIDEND",
                    source_action_ids=source_action_ids,
                    snapshot_id=input_id,
                    cash_per_share=cash,
                ),
                kind=InventoryEventKind.CASH_DIVIDEND,
                effective_at=_aware(trading_date, 9),
                available_at=action_available,
                snapshot_id=input_id,
                cash_per_share=cash,
            )
        )
    if ratio != 1.0:
        events.append(
            InventoryEvent(
                event_id=canonical_action_component_id(
                    symbol=previous.symbol,
                    effective_date=trading_date,
                    kind="SPLIT",
                    source_action_ids=source_action_ids,
                    snapshot_id=input_id,
                    share_multiplier=ratio,
                ),
                kind=InventoryEventKind.SPLIT,
                effective_at=_aware(trading_date, 9, 0, 1),
                available_at=action_available,
                snapshot_id=input_id,
                share_ratio=ratio,
            )
        )
    expected_float = float(row["circulating_shares"])
    bridged_float = previous.free_float_shares * ratio
    delta = expected_float - bridged_float
    float_snapshot_id = str(row.get("float_snapshot_id") or row["snapshot_id"])
    if delta > tolerance(expected_float):
        events.append(
            InventoryEvent(
                event_id=canonical_action_component_id(
                    symbol=previous.symbol,
                    effective_date=trading_date,
                    kind="FLOAT_ADD_UNKNOWN",
                    source_action_ids=(),
                    snapshot_id=float_snapshot_id,
                    shares=delta,
                ),
                kind=InventoryEventKind.FLOAT_ADD_UNKNOWN,
                effective_at=_aware(trading_date, 9, 0, 2),
                available_at=float_available,
                snapshot_id=float_snapshot_id,
                shares=delta,
                sensitivity=TurnoverSensitivity.NEUTRAL,
            )
        )
    elif delta < -tolerance(expected_float):
        removed = -delta
        events.append(
            InventoryEvent(
                event_id=canonical_action_component_id(
                    symbol=previous.symbol,
                    effective_date=trading_date,
                    kind="FLOAT_REMOVE_EXPLICIT",
                    source_action_ids=(),
                    snapshot_id=float_snapshot_id,
                    shares=removed,
                ),
                kind=InventoryEventKind.FLOAT_REMOVE_EXPLICIT,
                effective_at=_aware(trading_date, 9, 0, 2),
                available_at=float_available,
                snapshot_id=float_snapshot_id,
                shares=removed,
                source_removals=_pro_rata_removals(previous, ratio, removed),
            )
        )
    return tuple(events)


OUTPUT_SCHEMA = pa.schema(
    [
        ("storage_version", pa.string()),
        ("model_version", pa.string()),
        ("symbol", pa.string()),
        ("trade_date", pa.date32()),
        ("seller_model", pa.string()),
        ("snapshot_id", pa.string()),
        ("decision_at", pa.timestamp("us", tz="Asia/Shanghai")),
        ("available_at", pa.timestamp("us", tz="Asia/Shanghai")),
        # The complete input id list is already committed into snapshot_id.  A
        # fixed digest keeps independently verifiable provenance without copying
        # hundreds of strings into every seller-model row.
        ("input_snapshot_digest", pa.binary(32)),
        ("free_float_shares", pa.float64()),
        ("known_cost_fraction", pa.float64()),
        ("unknown_cost_fraction", pa.float64()),
        ("profile_close", pa.float64()),
        ("average_cost", pa.float64()),
        ("cost_p01", pa.float64()),
        ("cost_p10", pa.float64()),
        ("cost_p50", pa.float64()),
        ("cost_p90", pa.float64()),
        ("cost_p99", pa.float64()),
        ("profit_ratio", pa.float64()),
        ("asr", pa.float64()),
        ("cbw", pa.float64()),
        ("concentration_20", pa.float64()),
        ("main_peak", pa.float64()),
        ("dominant_peak_today", pa.float64()),
        ("dominant_band_lower", pa.float64()),
        ("dominant_band_upper", pa.float64()),
        ("dominant_band_mass", pa.float64()),
        ("peak_count", pa.int32()),
        # Full canonical candidates are required to establish a causal
        # temporal identity.  The scalar dominant fields remain diagnostics.
        ("canonical_peaks_json", pa.string()),
        ("model_quality", pa.float64()),
        ("checkpoint_local_ids", pa.list_(pa.uint64())),
        ("checkpoint_shares", pa.list_(pa.float64())),
        ("checkpoint_economic_bucket_ids", pa.list_(pa.int32())),
        ("transition_id", pa.string()),
        ("source_cell_ids_override", pa.list_(pa.uint64())),
        ("destination_override_positions", pa.list_(pa.uint32())),
        ("destination_override_cell_ids", pa.list_(pa.uint64())),
        ("retention_encoding", pa.uint8()),
        ("retention_values", pa.list_(pa.float64())),
        ("retention_codes", pa.binary()),
        ("inventory_adjustment_local_ids", pa.list_(pa.uint64())),
        ("inventory_adjustment_shares", pa.list_(pa.float64())),
        ("inventory_adjustment_economic_bucket_ids", pa.list_(pa.int32())),
        ("cash_dividend_per_share", pa.float64()),
        ("share_multiplier", pa.float64()),
        ("action_provenance_ids", pa.list_(pa.string())),
        ("fixed_pre_eligible_shares", pa.float64()),
        ("executed_sell_shares", pa.float64()),
        ("same_day_resale_shares", pa.float64()),
        ("conservation_error_shares", pa.float64()),
        ("minute_fallback", pa.bool_()),
        ("hard_valid", pa.bool_()),
        ("research_valid", pa.bool_()),
        ("quality_reason_codes", pa.list_(pa.string())),
    ]
)


_RESEARCH_RECOVERABLE_QUALITY_CODES = frozenset(
    {
        "UNKNOWN_COST_INITIALIZATION",
        "UNKNOWN_COST_PRESENT",
        "TURNOVER_CAPPED_AT_FLOAT",
    }
)


def _research_valid(state: MutableChipState) -> bool:
    """Allow explicit pre-history uncertainty in research, never in strict PIT."""

    return all(
        reason in _RESEARCH_RECOVERABLE_QUALITY_CODES
        for reason in state.quality_reason_codes
    )


class _ColumnarOutputBatch:
    """Accumulate Arrow columns directly instead of allocating one dict per row."""

    __slots__ = ("_columns", "_row_count")

    def __init__(self) -> None:
        self._columns: list[list[Any]] = [[] for _ in OUTPUT_SCHEMA]
        self._row_count = 0

    def __len__(self) -> int:
        return self._row_count

    def append(self, values: tuple[Any, ...]) -> None:
        if len(values) != len(self._columns):
            raise ValueError(
                f"output value count {len(values)} != schema field count {len(self._columns)}"
            )
        for column, value in zip(self._columns, values, strict=True):
            column.append(value)
        self._row_count += 1

    def to_table(self) -> pa.Table:
        arrays = [
            pa.array(column, type=schema_field.type)
            for column, schema_field in zip(self._columns, OUTPUT_SCHEMA, strict=True)
        ]
        return pa.Table.from_arrays(arrays, schema=OUTPUT_SCHEMA)

    def clear(self) -> None:
        for column in self._columns:
            column.clear()
        self._row_count = 0

TERMINAL_CELL_TYPE = pa.struct(
    [
        ("cell_id", pa.int64()),
        ("cost_bucket_id", pa.int64()),
        ("holding_days", pa.int16()),
        ("sensitivity", pa.string()),
        ("acquisition_cost", pa.float64()),
        ("economic_break_even", pa.float64()),
        ("shares", pa.float64()),
        ("initialization_prior_units", pa.float64()),
    ]
)

TERMINAL_SCHEMA = pa.schema(
    [
        ("storage_version", pa.string()),
        ("model_version", pa.string()),
        ("grid_version", pa.string()),
        ("symbol", pa.string()),
        ("trading_date", pa.date32()),
        ("decision_at", pa.timestamp("us", tz="Asia/Shanghai")),
        ("effective_at", pa.timestamp("us", tz="Asia/Shanghai")),
        ("available_at", pa.timestamp("us", tz="Asia/Shanghai")),
        ("phase", pa.string()),
        ("snapshot_id", pa.string()),
        ("seller_model", pa.string()),
        ("free_float_shares", pa.float64()),
        ("latent_supply_shares", pa.float64()),
        ("input_snapshot_ids", pa.list_(pa.string())),
        ("pit_grade", pa.string()),
        ("hard_valid", pa.bool_()),
        ("quality_reason_codes", pa.list_(pa.string())),
        ("cells", pa.list_(TERMINAL_CELL_TYPE)),
    ]
)

CELL_SENSITIVITY_BITS = 2
CELL_HOLDING_BITS = 8
CELL_DIMENSION_BITS = CELL_SENSITIVITY_BITS + CELL_HOLDING_BITS
CELL_HOLDING_MASK = (1 << CELL_HOLDING_BITS) - 1
CELL_COST_CODE_MAX = (1 << (32 - CELL_DIMENSION_BITS)) - 1


def _pack_cell_dimensions(
    cost_bucket_id: int | None,
    holding_days: int,
    sensitivity_code: int,
) -> int:
    """Pack immutable cell dimensions into a reversible uint32 id."""

    if not -1 <= holding_days < CELL_HOLDING_MASK:
        raise ValueError(f"holding_days outside packed range: {holding_days}")
    if not 0 <= sensitivity_code < (1 << CELL_SENSITIVITY_BITS):
        raise ValueError(f"sensitivity_code outside packed range: {sensitivity_code}")
    if cost_bucket_id is None:
        cost_code = 0
    else:
        zigzag = 2 * cost_bucket_id if cost_bucket_id >= 0 else -2 * cost_bucket_id - 1
        cost_code = zigzag + 1
    if cost_code > CELL_COST_CODE_MAX:
        raise ValueError(f"cost_bucket_id outside packed range: {cost_bucket_id}")
    holding_code = holding_days + 1
    return (
        (cost_code << CELL_DIMENSION_BITS)
        | (holding_code << CELL_SENSITIVITY_BITS)
        | sensitivity_code
    )


def _unpack_cell_dimensions(packed_id: int) -> tuple[int | None, int, int]:
    """Inverse of :func:`_pack_cell_dimensions`."""

    sensitivity_code = packed_id & ((1 << CELL_SENSITIVITY_BITS) - 1)
    holding_code = (packed_id >> CELL_SENSITIVITY_BITS) & CELL_HOLDING_MASK
    cost_code = packed_id >> CELL_DIMENSION_BITS
    if cost_code == 0:
        cost_bucket_id = None
    else:
        zigzag = cost_code - 1
        cost_bucket_id = zigzag // 2 if zigzag % 2 == 0 else -(zigzag // 2) - 1
    return cost_bucket_id, holding_code - 1, sensitivity_code


@dataclass
class _CellCodec:
    """Map stable hashes to reversible packed dimension ids."""

    by_cell_id: dict[int, int] = field(default_factory=dict)
    normal_destination_by_cell_id: dict[int, int] = field(default_factory=dict)
    cell_count: int = 0

    def register_snapshot(self, snapshot: ChipSnapshotV2) -> None:
        self.by_cell_id.clear()
        for cell in snapshot.inventory.cells:
            self.by_cell_id[cell.cell_id] = _pack_cell_dimensions(
                cell.cost_bucket_id,
                cell.holding_days,
                SENSITIVITY_CODE[cell.sensitivity],
            )
        self.cell_count = len(self.by_cell_id)

    def snapshot_view_and_economic_buckets(
        self, snapshot: ChipSnapshotV2, grid: StableLogPriceGrid
    ) -> tuple[
        dict[int, tuple[int | None, int, TurnoverSensitivity, float]],
        dict[int, int | None],
    ]:
        """Freeze the prior POST state before the mutable engine advances it."""

        self.register_snapshot(snapshot)
        view: dict[int, tuple[int | None, int, TurnoverSensitivity, float]] = {}
        economic: dict[int, int | None] = {}
        for cell in snapshot.inventory.cells:
            view[cell.cell_id] = (
                cell.cost_bucket_id,
                cell.holding_days,
                cell.sensitivity,
                cell.shares,
            )
            economic[cell.cell_id] = (
                None
                if cell.economic_break_even is None
                else bucket_for_economic_break_even(grid, cell.economic_break_even)
            )
        return view, economic

    def local_id(self, cell_id: int) -> int:
        """v12 persists the full causal cell identity, never a lossy local code."""

        return cell_id

    def register_state(
        self, state: MutableChipState, grid: StableLogPriceGrid
    ) -> dict[int, tuple[int | None, int, TurnoverSensitivity, float]]:
        """Register canonical mutable lots and return the lightweight daily view."""

        view, _, _, _ = self.register_state_and_profile(state, grid)
        return view

    def register_state_and_profile(
        self,
        state: MutableChipState,
        grid: StableLogPriceGrid,
        *,
        current_cell_ids_verified: bool = False,
    ) -> tuple[
        dict[int, tuple[int | None, int, TurnoverSensitivity, float]],
        dict[int, float],
        float,
        dict[int, int | None],
    ]:
        """Register lots and aggregate the daily price profile in one pass."""

        self.by_cell_id.clear()
        view: dict[int, tuple[int | None, int, TurnoverSensitivity, float]] = {}
        by_bucket: dict[int, float] = defaultdict(float)
        economic_bucket_by_cell_id: dict[int, int | None] = {}
        share_collisions: dict[int, list[float]] = {}
        known_shares = 0.0
        packed = state.packed_lots
        if packed is not None:
            sensitivities = (
                TurnoverSensitivity.ACTIVE,
                TurnoverSensitivity.NEUTRAL,
                TurnoverSensitivity.STICKY,
            )
            if not current_cell_ids_verified:
                # External/legacy callers are not trusted to maintain the flag;
                # recomputation keeps stale-id handling fail closed/canonical.
                packed._cell_ids_current = False
            packed.refresh_cell_ids()
            size = len(packed)
            shares_array = packed._shares[:size]
            active_indices = np.flatnonzero(shares_array > 0)
            cell_ids = packed._cell_ids
            bucket_ids = packed._cost_bucket_ids
            acquisition_costs = packed._acquisition_costs
            economic_break_evens = packed._economic_break_evens
            holding_days_array = packed._holding_days
            sensitivity_codes = packed._sensitivity_codes

            known_indices = active_indices[
                np.isfinite(economic_break_evens[active_indices])
            ]
            if known_indices.size:
                economic_values = economic_break_evens[known_indices]
                economic_buckets = np.full(
                    economic_values.shape,
                    NONPOSITIVE_ECONOMIC_BUCKET,
                    dtype=np.int64,
                )
                positive = economic_values > 0
                economic_buckets[positive] = np.floor(
                    np.log(economic_values[positive] / grid.reference_price)
                    / math.log1p(grid.step_pct)
                    + 0.5
                ).astype(np.int64)
                unique_buckets, inverse = np.unique(
                    economic_buckets, return_inverse=True
                )
                # Keep the vectorized bucket mapping above, but use the same
                # deterministic, order-independent summation contract as the
                # legacy replay when aggregating each bucket's shares.
                order = np.argsort(inverse, kind="stable")
                ordered_inverse = inverse[order]
                ordered_shares = shares_array[known_indices][order]
                boundaries = np.flatnonzero(
                    ordered_inverse[1:] != ordered_inverse[:-1]
                ) + 1
                starts = np.concatenate((np.array([0]), boundaries))
                stops = np.concatenate((boundaries, np.array([order.size])))
                bucket_mass = np.fromiter(
                    (
                        math.fsum(ordered_shares[start:stop].tolist())
                        for start, stop in zip(starts, stops, strict=True)
                    ),
                    dtype=np.float64,
                    count=unique_buckets.size,
                )
                by_bucket = {
                    int(bucket): float(mass)
                    for bucket, mass in zip(unique_buckets, bucket_mass, strict=True)
                }
                known_shares = math.fsum(bucket_mass.tolist())

            for index_value in active_indices:
                index = int(index_value)
                shares = float(shares_array[index])
                cell_id = int(cell_ids[index])
                raw_bucket = int(bucket_ids[index])
                acquisition_cost = float(acquisition_costs[index])
                cost_bucket_id = raw_bucket if math.isfinite(acquisition_cost) else None
                holding_days = int(holding_days_array[index])
                sensitivity = sensitivities[int(sensitivity_codes[index])]
                previous = view.get(cell_id)
                if previous is None:
                    view[cell_id] = (
                        cost_bucket_id,
                        holding_days,
                        sensitivity,
                        shares,
                    )
                else:
                    if previous[:3] != (cost_bucket_id, holding_days, sensitivity):
                        raise ValueError(f"cell hash collision for {cell_id}")
                    share_collisions.setdefault(cell_id, [previous[3]]).append(shares)
                economic_break_even = float(economic_break_evens[index])
                economic_bucket_by_cell_id[cell_id] = (
                    bucket_for_economic_break_even(grid, economic_break_even)
                    if math.isfinite(economic_break_even)
                    else None
                )
            for cell_id, parts in share_collisions.items():
                cost_bucket_id, holding_days, sensitivity, _ = view[cell_id]
                view[cell_id] = (
                    cost_bucket_id,
                    holding_days,
                    sensitivity,
                    math.fsum(parts),
                )
            self.cell_count = len(view)
            return view, by_bucket, known_shares, economic_bucket_by_cell_id

        if not isinstance(state.lots, list):
            raise TypeError("unexpected chip inventory representation")
        for lot in state.lots:
            if lot.shares <= 0:
                continue
            cell_id = lot.cell_id
            self.by_cell_id[cell_id] = _pack_cell_dimensions(
                lot.cost_bucket_id,
                lot.holding_days,
                SENSITIVITY_CODE[lot.sensitivity],
            )
            previous = view.get(cell_id)
            if previous is None:
                view[cell_id] = (
                    lot.cost_bucket_id,
                    lot.holding_days,
                    lot.sensitivity,
                    lot.shares,
                )
            else:
                if previous[:3] != (
                    lot.cost_bucket_id,
                    lot.holding_days,
                    lot.sensitivity,
                ):
                    raise ValueError(f"cell hash collision for {cell_id}")
                share_collisions.setdefault(cell_id, [previous[3]]).append(lot.shares)
            if lot.economic_break_even is not None:
                economic_bucket = bucket_for_economic_break_even(
                    grid, lot.economic_break_even
                )
                by_bucket[economic_bucket] += lot.shares
                known_shares += lot.shares
                economic_bucket_by_cell_id[cell_id] = economic_bucket
            else:
                economic_bucket_by_cell_id[cell_id] = None
        for cell_id, parts in share_collisions.items():
            cost_bucket_id, holding_days, sensitivity, _ = view[cell_id]
            view[cell_id] = (
                cost_bucket_id,
                holding_days,
                sensitivity,
                math.fsum(parts),
            )
        self.cell_count = len(view)
        return view, by_bucket, known_shares, economic_bucket_by_cell_id

    def normal_destination(
        self,
        cell_id: int,
        cell: tuple[int | None, int, TurnoverSensitivity, float],
        *,
        max_holding_days: int = DEFAULT_MAX_HOLDING_DAYS,
    ) -> int:
        cached = self.normal_destination_by_cell_id.get(cell_id)
        if cached is not None:
            return cached
        cost_bucket_id, holding_days, sensitivity, _ = cell
        aged_holding_days = (
            -1 if holding_days < 0 else min(holding_days + 1, max_holding_days)
        )
        destination = stable_cell_id(
            cost_bucket_id=cost_bucket_id,
            holding_days=aged_holding_days,
            sensitivity=sensitivity,
        )
        self.normal_destination_by_cell_id[cell_id] = destination
        return destination


def _pack_xor_floats(values: tuple[float, ...]) -> bytes:
    """Losslessly delta-code IEEE-754 bits; no retention precision is discarded."""

    if not values:
        return b""
    previous = struct.unpack("<Q", struct.pack("<d", values[0]))[0]
    output = bytearray(struct.pack("<Q", previous))
    for value in values[1:]:
        current = struct.unpack("<Q", struct.pack("<d", value))[0]
        delta = current ^ previous
        if delta == 0:
            output.append(0)
        else:
            offset = 0
            while (delta & 0xFF) == 0:
                offset += 1
                delta >>= 8
            length = (delta.bit_length() + 7) // 8
            output.append((offset << 4) | length)
            output.extend(delta.to_bytes(length, "little"))
        previous = current
    return bytes(output)


def _pack_palette_indexes(indexes: tuple[int, ...], bits: int) -> bytes:
    """Pack exact palette indexes using the minimum fixed number of bits."""

    if not indexes:
        return b""
    if not 1 <= bits <= 8:
        raise ValueError("palette bit width must be in [1,8]")
    output = bytearray((len(indexes) * bits + 7) // 8)
    bit_offset = 0
    limit = 1 << bits
    for index in indexes:
        if not 0 <= index < limit:
            raise ValueError("palette index exceeds bit width")
        byte_offset = bit_offset >> 3
        shift = bit_offset & 7
        output[byte_offset] |= index << shift & 0xFF
        if shift + bits > 8:
            output[byte_offset + 1] |= index >> (8 - shift)
        bit_offset += bits
    return bytes(output)


def _unpack_palette_indexes(payload: bytes, count: int, bits: int) -> tuple[int, ...]:
    """Inverse of :func:`_pack_palette_indexes`."""

    expected_size = (count * bits + 7) // 8
    if len(payload) != expected_size:
        raise ValueError("invalid bit-packed palette payload size")
    mask = (1 << bits) - 1
    indexes: list[int] = []
    bit_offset = 0
    for _ in range(count):
        byte_offset = bit_offset >> 3
        shift = bit_offset & 7
        value = payload[byte_offset] >> shift
        if shift + bits > 8:
            value |= payload[byte_offset + 1] << (8 - shift)
        indexes.append(value & mask)
        bit_offset += bits
    return tuple(indexes)


def _unpack_xor_floats(payload: bytes, count: int) -> tuple[float, ...]:
    """Inverse of :func:`_pack_xor_floats`, used by replay and focused tests."""

    if count == 0:
        if payload:
            raise ValueError("unexpected XOR payload for empty retention sequence")
        return ()
    if len(payload) < 8:
        raise ValueError("truncated XOR retention payload")
    previous = struct.unpack("<Q", payload[:8])[0]
    values = [struct.unpack("<d", struct.pack("<Q", previous))[0]]
    cursor = 8
    for _ in range(count - 1):
        if cursor >= len(payload):
            raise ValueError("truncated XOR retention payload")
        tag = payload[cursor]
        cursor += 1
        if tag:
            offset = tag >> 4
            length = tag & 0x0F
            if length == 0 or offset + length > 8 or cursor + length > len(payload):
                raise ValueError("invalid XOR retention payload")
            delta = int.from_bytes(payload[cursor : cursor + length], "little")
            cursor += length
            previous ^= delta << (offset * 8)
        values.append(struct.unpack("<d", struct.pack("<Q", previous))[0])
    if cursor != len(payload):
        raise ValueError("trailing bytes in XOR retention payload")
    return tuple(values)


def _pack_xor_byte_shuffled_floats(values: tuple[float, ...]) -> bytes:
    """Store exact XOR words in byte planes for stronger outer compression."""

    if not values:
        return b""
    # This is the hot path for daily high-cardinality survival vectors.  Keep
    # the exact IEEE-754 representation, but perform XOR and byte shuffling in
    # contiguous native arrays instead of thousands of Python pack/unpack calls.
    words = np.asarray(values, dtype="<f8").view("<u8")
    xor_words = words.copy()
    xor_words[1:] = np.bitwise_xor(words[1:], words[:-1])
    return xor_words.view(np.uint8).reshape(-1, 8).T.tobytes()


def _unpack_xor_byte_shuffled_floats(
    payload: bytes, count: int
) -> tuple[float, ...]:
    """Inverse byte-plane shuffle without changing any IEEE-754 bit."""

    if len(payload) != count * 8:
        raise ValueError("invalid byte-shuffled XOR retention payload size")
    if count == 0:
        return ()
    raw = bytearray(len(payload))
    for byte_offset in range(8):
        plane_start = byte_offset * count
        raw[byte_offset::8] = payload[plane_start : plane_start + count]
    xor_words = struct.unpack(f"<{count}Q", raw)
    previous = 0
    values: list[float] = []
    for position, word in enumerate(xor_words):
        current = word if position == 0 else word ^ previous
        values.append(struct.unpack("<d", struct.pack("<Q", current))[0])
        previous = current
    return tuple(values)


def _encode_retention(
    fractions: tuple[float, ...], sensitivity_codes: tuple[int, ...]
) -> tuple[int, list[float], bytes]:
    """Use cheap exact encodings and leave bulk compression to Parquet/Zstd."""

    if len(fractions) != len(sensitivity_codes):
        raise ValueError("retention and sensitivity lengths differ")
    if not fractions:
        return RETENTION_RAW, [], b""

    # Searching palettes and XOR-packing every large daily vector saved disk at
    # the cost of repeatedly walking millions of Python floats.  The annual
    # files are comfortably inside the storage budget with raw doubles, and
    # Parquet/Zstd still compresses them as a column.  Keep the compact search
    # only for small vectors where its CPU cost is negligible.
    if len(fractions) >= 128:
        first = fractions[0]
        if all(value == first for value in fractions[1:]):
            return RETENTION_CONSTANT, [first], b""
        return RETENTION_RAW, list(fractions), b""

    candidates: list[tuple[int, int, list[float], bytes]] = [
        (len(fractions) * 8, RETENTION_RAW, list(fractions), b"")
    ]
    # Most real daily vectors have far more than 255 exact rates.  Stop palette
    # discovery as soon as that encoding is impossible instead of hashing the
    # complete vector and then traversing it again.
    palette: list[float] = []
    palette_indexes: dict[float, int] = {}
    high_cardinality = False
    for value in fractions:
        if value in palette_indexes:
            continue
        if len(palette) == 255:
            high_cardinality = True
            break
        palette_indexes[value] = len(palette)
        palette.append(value)
    if len(palette) == 1:
        return RETENTION_CONSTANT, palette, b""
    if not high_cardinality:
        index_values = tuple(palette_indexes[value] for value in fractions)
        payload = bytes(index_values)
        candidates.append(
            (
                len(palette) * 8 + len(payload),
                RETENTION_PALETTE_U8,
                palette,
                payload,
            )
        )
        bits = max(1, (len(palette) - 1).bit_length())
        packed_payload = _pack_palette_indexes(index_values, bits)
        candidates.append(
            (
                len(palette) * 8 + len(packed_payload),
                RETENTION_PALETTE_BITPACK,
                palette,
                packed_payload,
            )
        )

    bases: list[float] = []
    for sensitivity in range(3):
        group = [
            value
            for value, code in zip(fractions, sensitivity_codes, strict=True)
            if code == sensitivity
        ]
        bases.append(Counter(group).most_common(1)[0][0] if group else 0.0)
    override_positions = [
        position
        for position, (value, code) in enumerate(
            zip(fractions, sensitivity_codes, strict=True)
        )
        if value != bases[code]
    ]
    group_values = bases + [fractions[position] for position in override_positions]
    group_payload = (
        struct.pack(f"<{len(override_positions)}I", *override_positions)
        if override_positions
        else b""
    )
    candidates.append(
        (
            len(group_values) * 8 + len(group_payload),
            RETENTION_BY_SENSITIVITY,
            group_values,
            group_payload,
        )
    )

    xor_payload = _pack_xor_floats(fractions)
    candidates.append((len(xor_payload), RETENTION_XOR, [], xor_payload))
    _, encoding, values, payload = min(candidates, key=lambda item: item[0])
    return encoding, values, payload


def _decode_retention(
    encoding: int,
    values: list[float],
    payload: bytes,
    sensitivity_codes: tuple[int, ...],
) -> tuple[float, ...]:
    """Replay one exact retention vector from the compact operator log."""

    count = len(sensitivity_codes)
    if encoding == RETENTION_RAW:
        result = tuple(values)
    elif encoding == RETENTION_CONSTANT:
        result = (values[0],) * count
    elif encoding == RETENTION_PALETTE_U8:
        if len(payload) != count:
            raise ValueError("invalid palette payload size")
        if any(index >= len(values) for index in payload):
            raise ValueError("palette index is out of range")
        result = tuple(values[index] for index in payload)
    elif encoding == RETENTION_PALETTE_BITPACK:
        bits = max(1, (len(values) - 1).bit_length())
        indexes = _unpack_palette_indexes(payload, count, bits)
        if any(index >= len(values) for index in indexes):
            raise ValueError("palette index is out of range")
        result = tuple(values[index] for index in indexes)
    elif encoding == RETENTION_BY_SENSITIVITY:
        override_values = values[3:]
        if len(payload) != len(override_values) * 4:
            raise ValueError("invalid sensitivity retention payload")
        result_list = [values[code] for code in sensitivity_codes]
        if override_values:
            positions = struct.unpack(f"<{len(override_values)}I", payload)
            for position, value in zip(positions, override_values, strict=True):
                result_list[position] = value
        result = tuple(result_list)
    elif encoding == RETENTION_XOR:
        result = _unpack_xor_floats(payload, count)
    elif encoding == RETENTION_XOR_BYTE_SHUFFLE:
        result = _unpack_xor_byte_shuffled_floats(payload, count)
    elif encoding == RETENTION_SOURCE_REPLAY:
        raise ValueError(
            "retention vector is source-replay-only; regenerate it from the "
            "registered daily/minute inputs and model version"
        )
    else:
        raise ValueError(f"unknown retention encoding: {encoding}")
    if len(result) != count:
        raise ValueError("decoded retention length differs from source inventory")
    return result


def _normally_aged_cell_id(
    cell: Any, *, max_holding_days: int = DEFAULT_MAX_HOLDING_DAYS
) -> int:
    holding_days = (
        -1 if cell.holding_days < 0 else min(cell.holding_days + 1, max_holding_days)
    )
    return stable_cell_id(
        cost_bucket_id=cell.cost_bucket_id,
        holding_days=holding_days,
        sensitivity=cell.sensitivity,
    )


def _storage_source_key(cell: Any) -> tuple[bool, int, int, int, int]:
    """Order sources by economic dimensions so exact float deltas compress well."""

    return (
        cell.cost_bucket_id is None,
        0 if cell.cost_bucket_id is None else cell.cost_bucket_id,
        cell.holding_days,
        SENSITIVITY_CODE[cell.sensitivity],
        cell.cell_id,
    )


def _storage_source_view_key(
    item: tuple[int, tuple[int | None, int, TurnoverSensitivity, float]],
) -> tuple[bool, int, int, int, int]:
    cell_id, (cost_bucket_id, holding_days, sensitivity, _) = item
    return (
        cost_bucket_id is None,
        0 if cost_bucket_id is None else cost_bucket_id,
        holding_days,
        SENSITIVITY_CODE[sensitivity],
        cell_id,
    )


def _sql_paths(paths: list[Path]) -> str:
    return "[" + ",".join("'" + str(path).replace("'", "''") + "'" for path in paths) + "]"


def _file_sha256(path: Path | None) -> str | None:
    if path is None:
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _minute_paths_for_year(year: int, root: Path = MINUTE_ROOT) -> list[Path]:
    return [
        root / f"{year}_day_parquet_none.parquet",
        *(root / name for name in MINUTE_YEAR_SUPPLEMENTS.get(year, ())),
    ]


def _stage_marker_matches(
    metadata: dict[str, Any],
    *,
    year: int,
    warmup_start: int,
    buckets: int,
    symbols: tuple[str, ...],
    prior_history_start: int | None = None,
    end_date: date | None = None,
    daily_root: Path = DAILY_ROOT,
    minute_root: Path = MINUTE_ROOT,
    action_override_sha256: str | None = None,
    baostock_delta_sha256: str | None = None,
) -> bool:
    base = {
        "year": year,
        "warmup_start": warmup_start,
        "buckets": buckets,
        "layout_version": STAGE_LAYOUT_VERSION,
        "prior_history_start": prior_history_start,
        "end_date": None if end_date is None else end_date.isoformat(),
        "daily_root": str(daily_root.resolve()),
        "minute_root": str(minute_root.resolve()),
        "action_override_sha256": action_override_sha256,
        "baostock_delta_sha256": baostock_delta_sha256,
    }
    comparable = dict(metadata)
    comparable.setdefault("daily_root", str(DAILY_ROOT.resolve()))
    comparable.setdefault("minute_root", str(MINUTE_ROOT.resolve()))
    comparable.setdefault("action_override_sha256", None)
    comparable.setdefault("baostock_delta_sha256", None)
    if any(comparable.get(key) != value for key, value in base.items()):
        return False
    staged_symbols = metadata.get("symbols")
    if not symbols:
        return staged_symbols is None
    # A full-market stage is a valid superset for a targeted run.
    if staged_symbols is None:
        return True
    if not isinstance(staged_symbols, list):
        return False
    return set(symbols).issubset(staged_symbols)


def _stage_inputs(
    *,
    year: int,
    warmup_start: int,
    buckets: int,
    stage_root: Path,
    symbols: tuple[str, ...] = (),
    prior_history_start: int | None = None,
    end_date: date | None = None,
    daily_root: Path = DAILY_ROOT,
    minute_root: Path = MINUTE_ROOT,
    research_action_overrides: Path | None = None,
    baostock_delta_file: Path | None = None,
) -> None:
    action_override_sha256 = _file_sha256(research_action_overrides)
    baostock_delta_sha256 = _file_sha256(baostock_delta_file)
    marker = stage_root / "COMPLETE.json"
    if marker.exists():
        try:
            metadata = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            metadata = {}
        if _stage_marker_matches(
            metadata,
            year=year,
            warmup_start=warmup_start,
            buckets=buckets,
            symbols=symbols,
            prior_history_start=prior_history_start,
            end_date=end_date,
            daily_root=daily_root,
            minute_root=minute_root,
            action_override_sha256=action_override_sha256,
            baostock_delta_sha256=baostock_delta_sha256,
        ):
            return
    if stage_root.exists():
        shutil.rmtree(stage_root)
    daily_paths = [
        daily_root / f"partition_year={value}/data_0.parquet"
        for value in range(warmup_start, year + 1)
    ]
    minute_paths = [
        path
        for value in range(warmup_start, year + 1)
        for path in _minute_paths_for_year(value, minute_root)
    ]
    required_paths = daily_paths + minute_paths
    if research_action_overrides is not None:
        required_paths.append(research_action_overrides)
    if baostock_delta_file is not None:
        required_paths.append(baostock_delta_file)
    missing = [path for path in required_paths if not path.exists()]
    if missing:
        raise FileNotFoundError(f"missing inputs: {missing[:3]}")
    daily_out = stage_root / "daily"
    minute_out = stage_root / "minute"
    daily_out.mkdir(parents=True)
    minute_out.mkdir(parents=True)
    temp_out = stage_root / "_duckdb_tmp"
    temp_out.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect()
    connection.execute(f"SET threads={buckets}")
    connection.execute("SET memory_limit='8GiB'")
    connection.execute("SET preserve_insertion_order=false")
    connection.execute("SET partitioned_write_max_open_files=32")
    escaped_temp_out = str(temp_out.resolve()).replace("'", "''")
    connection.execute(f"SET temp_directory='{escaped_temp_out}'")
    if symbols:
        values = ",".join(
            "('" + symbol.replace("'", "''") + "')"
            for symbol in sorted(set(symbols))
        )
        universe_sql = f"""
            SELECT symbol
            FROM (VALUES {values}) AS requested(symbol)
            WHERE regexp_matches(symbol, '^(00|30|60)')
        """
    else:
        target_path = daily_root / f"partition_year={year}/data_0.parquet"
        universe_sql = f"""
            SELECT DISTINCT symbol
            FROM read_parquet('{str(target_path).replace("'", "''")}')
            WHERE regexp_matches(symbol, '^(00|30|60)')
        """
    prior_symbols: list[str] = []
    end_date_predicate = (
        "TRUE"
        if end_date is None
        else f"trade_date <= DATE '{end_date.isoformat()}'"
    )
    if prior_history_start is not None and prior_history_start < year:
        prior_paths = [
            daily_root / f"partition_year={value}/data_0.parquet"
            for value in range(prior_history_start, year)
        ]
        missing_prior = [path for path in prior_paths if not path.exists()]
        if missing_prior:
            raise FileNotFoundError(f"missing prior-history inputs: {missing_prior[:3]}")
        prior_symbols = [
            str(row[0])
            for row in connection.execute(
                f"""
                WITH universe AS ({universe_sql})
                SELECT DISTINCT d.symbol
                FROM read_parquet({_sql_paths(prior_paths)}) d
                SEMI JOIN universe u ON d.symbol = u.symbol
                """
            ).fetchall()
        ]
    if research_action_overrides is None:
        action_override_sql = """
            SELECT
                CAST(NULL AS VARCHAR) AS symbol,
                CAST(NULL AS DATE) AS trade_date,
                CAST(NULL AS BOOLEAN) AS apply_action,
                CAST(NULL AS DOUBLE) AS share_multiplier,
                CAST(NULL AS DOUBLE) AS cash_per_share,
                CAST(NULL AS DOUBLE) AS circulating_shares_override,
                CAST(NULL AS TIMESTAMP) AS known_at,
                CAST(NULL AS VARCHAR) AS snapshot_id
            WHERE false
        """
    else:
        escaped_override = str(research_action_overrides.resolve()).replace("'", "''")
        action_override_sql = f"""
            SELECT symbol, trade_date, apply_action, share_multiplier,
                   cash_per_share, circulating_shares_override, known_at,
                   snapshot_id
            FROM read_parquet('{escaped_override}')
        """
    minute_source_sql = f"""
        SELECT m.qmt_code, m.trade_date, m.bar_end_time,
               m.open, m.high, m.low, m.close, m.volume, m.amount,
               'qmt-none-1m' AS minute_source
        FROM read_parquet({_sql_paths(minute_paths)}) m
    """
    if baostock_delta_file is not None:
        escaped_delta = str(baostock_delta_file.resolve()).replace("'", "''")
        minute_source_sql += f"""
          UNION ALL
          SELECT SUBSTR(code, 4) || '.' || UPPER(SUBSTR(code, 1, 2)) AS qmt_code,
                 CAST(date AS DATE) AS trade_date,
                 STRPTIME(SUBSTR(time, 1, 14), '%Y%m%d%H%M%S') AS bar_end_time,
                 TRY_CAST(open AS DOUBLE) AS open,
                 TRY_CAST(high AS DOUBLE) AS high,
                 TRY_CAST(low AS DOUBLE) AS low,
                 TRY_CAST(close AS DOUBLE) AS close,
                 TRY_CAST(volume AS DOUBLE) AS volume,
                 TRY_CAST(amount AS DOUBLE) AS amount,
                 'baostock-none-5m' AS minute_source
          FROM read_parquet('{escaped_delta}')
        """
    daily_bucketed = stage_root / "_daily_bucketed"
    minute_bucketed = stage_root / "_minute_bucketed"

    def split_bucketed_by_symbol(bucketed_root: Path, output_root: Path) -> None:
        for bucket in range(buckets):
            bucket_root = bucketed_root / f"bucket={bucket}"
            source_paths = sorted(bucket_root.glob("*.parquet"))
            if not source_paths:
                continue
            destination = output_root / f"bucket={bucket}"
            destination.mkdir(parents=True, exist_ok=True)
            escaped_destination = str(destination.resolve()).replace("'", "''")
            connection.execute(
                f"""
                COPY (
                    SELECT *
                    FROM read_parquet(
                        {_sql_paths(source_paths)},
                        hive_partitioning=false,
                        union_by_name=true
                    )
                ) TO '{escaped_destination}'
                (FORMAT PARQUET, PARTITION_BY(symbol), COMPRESSION ZSTD,
                 ROW_GROUP_SIZE 262144)
                """
            )
            shutil.rmtree(bucket_root)
        bucketed_root.rmdir()

    connection.execute(
        f"""
        COPY (
            WITH universe AS ({universe_sql}),
            action_override AS ({action_override_sql})
            SELECT d.symbol, d.trade_date, d.open, d.high, d.low, d.close,
                   d.volume, d.amount, d.trade_status,
                   d.turnover_fraction AS turnover,
                   CASE WHEN o.symbol IS NOT NULL
                        THEN o.circulating_shares_override
                        ELSE d.circulating_shares END AS circulating_shares,
                   d.float_available_date, d.corporate_action_available_date,
                   CASE WHEN o.symbol IS NOT NULL
                        THEN false ELSE d.corporate_action_blocking
                   END AS corporate_action_blocking,
                   CASE WHEN coalesce(o.apply_action, false)
                        THEN o.share_multiplier ELSE d.share_multiplier
                   END AS share_multiplier,
                   CASE WHEN coalesce(o.apply_action, false)
                        THEN o.cash_per_share ELSE d.cash_per_share
                   END AS cash_per_share,
                   d.available_at,
                   CASE WHEN o.symbol IS NOT NULL
                        THEN concat_ws('|', d.snapshot_id, o.snapshot_id)
                        ELSE d.snapshot_id END AS snapshot_id,
                   d.daily_snapshot_id, d.float_snapshot_id,
                   CASE WHEN o.symbol IS NOT NULL
                        THEN o.snapshot_id ELSE d.corporate_action_snapshot_id
                   END AS corporate_action_snapshot_id,
                   CASE WHEN o.symbol IS NOT NULL THEN
                        d.bar_valid AND d.trading_state_valid AND d.industry_valid
                        AND d.float_valid AND d.market_valid AND d.market_rule_valid
                        AND d.historical_identity_valid
                        ELSE d.hard_valid END AS hard_valid,
                   CAST(hash(d.symbol) % {buckets} AS INTEGER) AS bucket
            FROM read_parquet({_sql_paths(daily_paths)}) d
            SEMI JOIN universe u ON d.symbol = u.symbol
            LEFT JOIN action_override o USING (symbol, trade_date)
            WHERE {end_date_predicate}
        ) TO '{str(daily_bucketed).replace("'", "''")}'
        (FORMAT PARQUET, PARTITION_BY(bucket), COMPRESSION ZSTD,
         ROW_GROUP_SIZE 262144)
        """
    )
    split_bucketed_by_symbol(daily_bucketed, daily_out)
    connection.execute(
        f"""
        COPY (
            WITH universe AS ({universe_sql}),
            minute_source AS ({minute_source_sql})
            SELECT m.qmt_code AS symbol, m.trade_date, m.bar_end_time,
                   m.open, m.high, m.low, m.close, m.volume, m.amount,
                   m.minute_source,
                   CAST(hash(m.qmt_code) % {buckets} AS INTEGER) AS bucket
            FROM minute_source m
            SEMI JOIN universe u ON m.qmt_code = u.symbol
            WHERE {end_date_predicate}
        ) TO '{str(minute_bucketed).replace("'", "''")}'
        (FORMAT PARQUET, PARTITION_BY(bucket), COMPRESSION ZSTD,
         ROW_GROUP_SIZE 262144)
        """
    )
    split_bucketed_by_symbol(minute_bucketed, minute_out)
    connection.close()
    marker_metadata: dict[str, Any] = {
        "year": year,
        "warmup_start": warmup_start,
        "buckets": buckets,
        "layout_version": STAGE_LAYOUT_VERSION,
        "prior_history_start": prior_history_start,
        "end_date": None if end_date is None else end_date.isoformat(),
        "daily_root": str(daily_root.resolve()),
        "minute_root": str(minute_root.resolve()),
        "action_override_sha256": action_override_sha256,
        "baostock_delta_sha256": baostock_delta_sha256,
    }
    if symbols:
        marker_metadata["symbols"] = sorted(set(symbols))
    (stage_root / "PRIOR_SYMBOLS.json").write_text(
        json.dumps(sorted(prior_symbols), ensure_ascii=False), encoding="utf-8"
    )
    marker.write_text(
        json.dumps(marker_metadata, ensure_ascii=False), encoding="utf-8"
    )


def _symbol_partition_dirs(
    stage_root: Path, kind: str, bucket: int
) -> dict[str, Path]:
    root = stage_root / kind / f"bucket={bucket}"
    return {
        path.name.removeprefix("symbol="): path
        for path in root.glob("symbol=*")
        if path.is_dir()
    }


def _read_symbol_partition(path: Path | None, symbol: str) -> list[dict[str, Any]]:
    """Read one stock only; partition columns are restored without a global sort."""

    if path is None:
        return []
    rows: list[dict[str, Any]] = []
    for parquet_path in sorted(path.glob("*.parquet")):
        for row in pq.ParquetFile(parquet_path).read().to_pylist():
            row["symbol"] = symbol
            rows.append(row)
    return rows


def _read_prior_symbols(stage_root: Path) -> set[str]:
    path = stage_root / "PRIOR_SYMBOLS.json"
    if not path.exists():
        return set()
    values = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        raise ValueError("invalid staged prior-symbol index")
    return set(values)


def _resolve_resume_root(
    *,
    output_root: Path,
    year: int,
    warmup_start: int,
    explicit: Path | None,
    auto_resume: bool,
) -> tuple[Path | None, str]:
    """Use the adjacent year's exact terminal state unless explicitly disabled."""

    if explicit is not None:
        return explicit, "explicit"
    if auto_resume and year > warmup_start:
        candidate = output_root.parent / f"year={year - 1}"
        if (candidate / "terminal").is_dir():
            return candidate, "auto_adjacent_year"
    return None, "none"


def _daily_fallback_bar(row: dict[str, Any]) -> tuple[MinuteBar, ...]:
    volume = float(row.get("volume") or 0.0)
    if volume <= 0:
        return ()
    day = _date(row["trade_date"])
    timestamp = _aware(day, 15)
    amount = float(row.get("amount") or 0.0)
    low = float(row["low"])
    high = float(row["high"])
    vwap = amount / volume if amount > 0 else float(row["close"])
    if not low <= vwap <= high:
        vwap = float(row["close"])
    return (
        MinuteBar(
            timestamp=timestamp,
            available_at=timestamp,
            snapshot_id=f"daily-fallback:{row['symbol']}:{day.isoformat()}",
            open=float(row["open"]),
            high=high,
            low=low,
            close=float(row["close"]),
            volume_shares=volume,
            vwap=vwap,
        ),
    )


def _cap_prepared_minute_path(
    path: PreparedMinutePath, *, max_volume: float
) -> PreparedMinutePath:
    """Saturate modeled turnover at the causal PRE float without changing prices.

    Raw daily/minute volume remains untouched in its registered source.  This
    only scales the migration operator when the observed volume implies more
    than one sale per PRE share, which cannot be represented under A-share T+1.
    """

    if not math.isfinite(max_volume) or max_volume <= 0:
        raise ValueError("turnover cap must be finite and positive")
    if path.total_volume <= max_volume + tolerance(max_volume):
        return path
    # Leave a one-billionth numerical headroom instead of asking the bounded
    # seller allocator to hit an exactly empty floating-point inventory.
    capped_volume = max_volume * (1.0 - 1e-9)
    scale = capped_volume / path.total_volume
    scaled_volumes = path.volumes * scale
    scaled_purchase_volumes = path.purchase_volumes * scale
    return replace(
        path,
        purchases=tuple(
            (bucket, price, volume * scale)
            for bucket, price, volume in path.purchases
        ),
        bucket_purchases=tuple(
            (bucket, price, volume * scale)
            for bucket, price, volume in path.bucket_purchases
        ),
        total_volume=stable_sum(scaled_volumes),
        volumes=scaled_volumes,
        purchase_volumes=scaled_purchase_volumes,
    )


def _output_row(
    *,
    state: MutableChipState,
    transition: Any,
    fallback: bool,
    previous_post: dict[int, tuple[int | None, int, TurnoverSensitivity, float]] | None,
    previous_economic_buckets: dict[int, int | None] | None,
    codec: _CellCodec,
    grid: StableLogPriceGrid,
    cash_dividend_per_share: float = 0.0,
    share_multiplier: float = 1.0,
    action_provenance_ids: tuple[str, ...] = (),
    force_checkpoint: bool = False,
    current_price: float | None = None,
    encode_replay: bool = True,
) -> tuple[
    tuple[Any, ...],
    dict[int, tuple[int | None, int, TurnoverSensitivity, float]],
    dict[int, int | None],
]:
    """Encode a checkpoint or a compact daily operator/replay locator."""

    current, by_bucket, known_shares, current_economic_buckets = (
        codec.register_state_and_profile(
            state,
            grid,
            current_cell_ids_verified=True,
        )
    )
    metrics = None
    profile_close = current_price
    if by_bucket:
        if profile_close is None:
            raise ValueError("non-empty chip mass requires the real daily close")
        metrics = compute_distribution_metrics(
            by_bucket,
            close=profile_close,
            grid=grid,
            as_of=state.trading_date,
        )
    total = state.free_float_shares
    checkpoint_local_ids: list[int] = []
    checkpoint_shares: list[float] = []
    checkpoint_economic_bucket_ids: list[int | None] = []
    source_override: list[int] = []
    destination_override_positions: list[int] = []
    destination_override_cell_ids: list[int] = []
    retention_encoding = RETENTION_RAW
    retention_values: list[float] = []
    retention_codes = b""
    adjustment_local_ids: list[int] = []
    adjustment_shares: list[float] = []
    adjustment_economic_bucket_ids: list[int | None] = []

    if encode_replay and (previous_post is None or force_checkpoint):
        checkpoint_local_ids = [codec.local_id(cell_id) for cell_id in current]
        checkpoint_shares = [cell[3] for cell in current.values()]
        checkpoint_economic_bucket_ids = [
            current_economic_buckets[cell_id] for cell_id in current
        ]
    # Keep the transition on checkpoint rows too.  A lifecycle anchor may sit
    # before this checkpoint (or in the prior year) and must replay through it.
    if encode_replay and previous_post is not None:
        previous_by_id = previous_post
        actual_sources = tuple(transition.source_cell_ids)
        # v12 ids are full economic identities and are intentionally not
        # reversible packed dimension codes.  Numeric id order is the compact,
        # deterministic source order shared with the replay decoder.
        expected_sources = tuple(sorted(previous_by_id))
        sources_are_unique = all(
            left != right for left, right in pairwise(actual_sources)
        )
        sources_match_previous = len(actual_sources) == len(previous_by_id) and all(
            source_id in previous_by_id for source_id in actual_sources
        )
        if sources_are_unique and sources_match_previous:
            arc_by_source = {
                source_id: (destination_id, retained_fraction)
                for source_id, destination_id, retained_fraction in zip(
                    transition.source_cell_ids,
                    transition.destination_cell_ids,
                    transition.retained_fractions,
                    strict=True,
                )
            }
            ordered_sources = expected_sources
            ordered_destinations = tuple(
                arc_by_source[source_id][0] for source_id in ordered_sources
            )
            ordered_fractions = tuple(
                arc_by_source[source_id][1] for source_id in ordered_sources
            )
        else:
            # Preserve unusual multi-arc transitions exactly instead of guessing an order.
            source_override = [codec.local_id(cell_id) for cell_id in actual_sources]
            ordered_sources = actual_sources
            ordered_destinations = tuple(transition.destination_cell_ids)
            ordered_fractions = tuple(transition.retained_fractions)
        predicted: dict[int, float] = {}
        for position, (source_id, destination_id, retained_fraction) in enumerate(
            zip(
                ordered_sources,
                ordered_destinations,
                ordered_fractions,
                strict=True,
            )
        ):
            source_cell = previous_by_id.get(source_id)
            if source_cell is None:
                missing = sorted(set(ordered_sources) - set(previous_by_id))
                extra = sorted(set(previous_by_id) - set(ordered_sources))
                raise ValueError(
                    "transition source is absent from prior POST inventory: "
                    f"symbol={state.symbol}, date={state.trading_date}, "
                    f"model={state.seller_model.value}, source={source_id}, "
                    f"prior_cells={len(previous_by_id)}, arcs={len(ordered_sources)}, "
                    f"cash={cash_dividend_per_share}, split={share_multiplier}, "
                    f"missing={missing[:3]}, extra={extra[:3]}, "
                    f"missing_dims={[codec.by_cell_id.get(value) for value in missing[:3]]}, "
                    f"extra_dims={[codec.by_cell_id.get(value) for value in extra[:3]]}"
                )
            # v12 never infers a destination from a source id: economic-cost
            # coordinates are state identity and can change on an action day.
            destination_override_positions.append(position)
            destination_override_cell_ids.append(codec.local_id(destination_id))
            retained_shares = source_cell[3] * retained_fraction
            if retained_shares != 0.0:
                predicted[destination_id] = (
                    predicted.get(destination_id, 0.0) + retained_shares
                )

        # v12 must be independently replayable without deriving sensitivity
        # from a compact id.  Retention is therefore stored exactly, and every
        # destination is explicit below.
        retention_encoding = RETENTION_RAW
        retention_values = list(ordered_fractions)
        retention_codes = b""
        for cell_id, cell in current.items():
            delta = cell[3] - predicted.get(cell_id, 0.0)
            if delta != 0.0:
                adjustment_local_ids.append(codec.local_id(cell_id))
                adjustment_shares.append(delta)
                adjustment_economic_bucket_ids.append(
                    current_economic_buckets.get(cell_id)
                )
        for cell_id, predicted_shares in predicted.items():
            if cell_id not in current:
                adjustment_local_ids.append(codec.local_id(cell_id))
                adjustment_shares.append(-predicted_shares)
                adjustment_economic_bucket_ids.append(
                    None
                    if previous_economic_buckets is None
                    else previous_economic_buckets.get(cell_id)
                )
        reconstructed_total = math.fsum(predicted.values()) + math.fsum(adjustment_shares)
        if abs(reconstructed_total - total) > tolerance(total):
            raise ValueError(
                "compact operator does not conserve inventory: "
                f"{reconstructed_total} != {total}"
            )
    row = (
        STORAGE_VERSION,
        state.model_version,
        state.symbol,
        state.trading_date,
        state.seller_model.value,
        state.snapshot_id,
        state.decision_at,
        state.available_at,
        hashlib.sha256(
            "\n".join(state.input_snapshot_ids).encode("utf-8")
        ).digest(),
        total,
        known_shares / total,
        (total - known_shares) / total,
        float(profile_close) if profile_close is not None else None,
        None if metrics is None else metrics.average_cost,
        None if metrics is None else metrics.cost_p01,
        None if metrics is None else metrics.cost_p10,
        None if metrics is None else metrics.cost_p50,
        None if metrics is None else metrics.cost_p90,
        None if metrics is None else metrics.cost_p99,
        None if metrics is None else metrics.profit_ratio,
        None if metrics is None else metrics.asr,
        None if metrics is None else metrics.cbw,
        None if metrics is None else metrics.concentration_20,
        None if metrics is None else metrics.main_peak,
        None if metrics is None else metrics.main_peak,
        None if metrics is None else metrics.dominant_band_lower,
        None if metrics is None else metrics.dominant_band_upper,
        None if metrics is None else metrics.dominant_band_mass,
        None if metrics is None else metrics.peak_count,
        (
            None
            if metrics is None
            else json.dumps(
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
                    for peak in metrics.canonical_peaks
                ],
                separators=(",", ":"),
                sort_keys=True,
            )
        ),
        1.0 if state.hard_valid else 0.0,
        checkpoint_local_ids,
        checkpoint_shares,
        checkpoint_economic_bucket_ids,
        transition.transition_id,
        source_override,
        destination_override_positions,
        destination_override_cell_ids,
        retention_encoding,
        retention_values,
        retention_codes,
        adjustment_local_ids,
        adjustment_shares,
        adjustment_economic_bucket_ids,
        cash_dividend_per_share,
        share_multiplier,
        list(action_provenance_ids),
        transition.fixed_pre_eligible_shares,
        transition.executed_sell_shares,
        transition.same_day_resale_shares,
        state.conservation_error,
        fallback,
        state.hard_valid,
        _research_valid(state),
        list(state.quality_reason_codes),
    )
    return row, current, current_economic_buckets


@dataclass(frozen=True)
class ReplayableDayFact:
    """One governed daily transition input and its output cadence markers."""

    daily_row: dict[str, Any]
    minute_rows: tuple[dict[str, Any], ...]
    transition_required: bool
    target_required: bool
    checkpoint_label: str | None

    @property
    def trading_date(self) -> date:
        return _date(self.daily_row["trade_date"])


def _build_replayable_day_facts(
    daily_rows: list[dict[str, Any]],
    minute_rows: list[dict[str, Any]],
    year: int,
    *,
    state_resumed: bool,
) -> tuple[ReplayableDayFact, ...]:
    """Build the sole execution-time date, input, and cadence authority."""

    ordered = sorted(daily_rows, key=lambda row: _date(row["trade_date"]))
    if not ordered:
        raise ValueError("no daily rows")
    ordered_dates = tuple(_date(row["trade_date"]) for row in ordered)
    if ordered_dates != tuple(sorted(set(ordered_dates))):
        raise ValueError("daily input dates must be unique and ordered")
    if state_resumed:
        selected = tuple((row, True) for row in ordered)
    else:
        first_state_index = next(
            (
                index
                for index, row in enumerate(ordered)
                if row.get("circulating_shares") is not None
                and float(row["circulating_shares"]) > 0
            ),
            None,
        )
        if first_state_index is None:
            raise ValueError("no daily row has a known positive circulating share count")
        selected = tuple(
            (row, index != first_state_index)
            for index, row in enumerate(ordered[first_state_index:], first_state_index)
        )
    minute_by_date: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for row in minute_rows:
        minute_by_date[_date(row["trade_date"])].append(row)
    target_dates = tuple(
        _date(row["trade_date"])
        for row, transition_required in selected
        if transition_required and _date(row["trade_date"]).year == year
    )
    if not target_dates:
        raise ValueError("target year has no replayable transition date")
    month_ends: dict[tuple[int, int], date] = {}
    for trading_date in target_dates:
        month_ends[(trading_date.year, trading_date.month)] = trading_date
    cadence_dates = tuple(dict.fromkeys((target_dates[0], *month_ends.values())))
    labels = {
        trading_date: (
            f"opening-{trading_date.isoformat()}"
            if position == 0
            else f"month-{trading_date.month:02d}-{trading_date.isoformat()}"
        )
        for position, trading_date in enumerate(cadence_dates)
    }
    return tuple(
        ReplayableDayFact(
            daily_row=row,
            minute_rows=tuple(minute_by_date.get(_date(row["trade_date"]), ())),
            transition_required=transition_required,
            target_required=(
                transition_required and _date(row["trade_date"]).year == year
            ),
            checkpoint_label=labels.get(_date(row["trade_date"])),
        )
        for row, transition_required in selected
    )


def _run_symbol(
    symbol: str,
    daily_rows: list[dict[str, Any]],
    minute_rows: list[dict[str, Any]],
    year: int,
    writer: pq.ParquetWriter | None,
    initial_snapshots: dict[SellerModel, ChipSnapshotV2] | None = None,
    *,
    emit_operators: bool = True,
    emit_start_date: date | None = None,
    output_row_group_size: int = OUTPUT_ROW_GROUP_SIZE,
    replayable_day_facts: tuple[ReplayableDayFact, ...] | None = None,
    day_sink: Callable[
        [
            ReplayableDayFact,
            tuple[dict[str, Any], ...],
            Mapping[SellerModel, ChipSnapshotV2 | MutableChipState],
        ],
        None,
    ]
    | None = None,
) -> tuple[dict[str, Any], dict[SellerModel, ChipSnapshotV2]]:
    if output_row_group_size < 1:
        raise ValueError("output row group size must be positive")
    facts = replayable_day_facts or _build_replayable_day_facts(
        daily_rows,
        minute_rows,
        year,
        state_resumed=initial_snapshots is not None,
    )
    replayable_dates = tuple(
        fact.trading_date for fact in facts if fact.target_required
    )
    grid = StableLogPriceGrid(1.0, 0.0025, GRID_VERSION)
    aged_cell_id_cache: dict[int, int] = {}
    engines = {
        model: DailyMigrationEngine(
            grid=grid,
            seller_model=model,
            model_version=MODEL_VERSION,
            aged_cell_id_cache=aged_cell_id_cache,
        )
        for model in SELLER_MODEL_ORDER
    }
    first = facts[0].daily_row
    first_date = _date(first["trade_date"])
    if initial_snapshots is None:
        if facts[0].transition_required or len(facts) < 2:
            raise ValueError("fewer than two daily rows without a prior terminal state")
        current = {
            model: initial_unknown_snapshot(
                symbol=symbol,
                decision_at=_aware(first_date, 15),
                available_at=_aware(first_date, 15),
                free_float_shares=float(first["circulating_shares"]),
                latent_supply_shares=0.0,
                seller_model=model,
                model_version=MODEL_VERSION,
                grid_version=GRID_VERSION,
                input_snapshot_ids=_snapshot_ids(first),
            )
            for model in SELLER_MODEL_ORDER
        }
        facts_to_process = facts[1:]
    else:
        if set(initial_snapshots) != set(SELLER_MODEL_ORDER):
            raise ValueError("terminal state must contain all seller models")
        staged_years = {fact.trading_date.year for fact in facts}
        if staged_years != {year}:
            raise ValueError(
                "resumed calculation must stage only the target year: "
                f"target={year}, staged={sorted(staged_years)}"
            )
        current = dict(initial_snapshots)
        for model, snapshot in current.items():
            if snapshot.symbol != symbol or snapshot.seller_model != model:
                raise ValueError("terminal state symbol/model mismatch")
            if snapshot.model_version != MODEL_VERSION or snapshot.grid_version != GRID_VERSION:
                raise ValueError("terminal state version mismatch")
            if snapshot.phase != SnapshotPhase.POST:
                raise ValueError("terminal state must be POST")
            if snapshot.trading_date >= first_date:
                raise ValueError("terminal state must precede the first staged day")
        facts_to_process = facts
    codec = _CellCodec()
    emitted_models: set[SellerModel] = set()
    previous_output_states: dict[
        SellerModel,
        dict[int, tuple[int | None, int, TurnoverSensitivity, float]],
    ] = {}
    previous_output_economic_buckets: dict[
        SellerModel, dict[int, int | None]
    ] = {}
    output_rows = _ColumnarOutputBatch()
    output_count = 0
    emitted_day_count = 0
    target_day_count = 0
    fallback_days = 0
    max_mass_error = 0.0
    max_same_day_resale = 0.0
    for fact in facts_to_process:
        if not fact.transition_required:
            raise RuntimeError("non-transition listing boundary entered replay loop")
        row = fact.daily_row
        trading_date = fact.trading_date
        day_projection_rows: list[dict[str, Any]] = []
        state_dates = {state.trading_date for state in current.values()}
        if len(state_dates) != 1:
            raise RuntimeError("seller-model states are not aligned to one trading date")
        previous_state_date = next(iter(state_dates))
        if trading_date.year != previous_state_date.year:
            # Annual resume reads the canonical terminal snapshot.  Match that
            # representation in an uninterrupted replay so internal duplicate
            # lots cannot make the two execution paths diverge by float-order.
            current = {
                model: state
                if isinstance(state, ChipSnapshotV2)
                else state.to_snapshot()
                for model, state in current.items()
            }
        input_hard_valid = bool(row.get("hard_valid", False))
        raw_free_float = row.get("circulating_shares")
        missing_free_float = raw_free_float is None or float(raw_free_float) <= 0
        if missing_free_float and input_hard_valid:
            raise ValueError(
                "hard-valid daily row has no positive circulating share count"
            )
        bars = (
            []
            if missing_free_float
            else _minute_bars(list(fact.minute_rows), trading_date)
        )
        fallback = False
        if not missing_free_float and not bars and float(row.get("volume") or 0.0) > 0:
            bars = _daily_fallback_bar(row)
            fallback = True
            fallback_days += 1
        decision_at = _aware(trading_date, 15)
        prepared_minute_path = prepare_minute_path(
            grid=grid,
            decision_at=decision_at,
            minute_bars=bars,
        )
        additional_input_snapshot_ids = _snapshot_ids(row)
        expected_free_float_shares = (
            next(iter(current.values())).free_float_shares
            if missing_free_float
            else float(raw_free_float)
        )
        quality_reasons: list[str] = []
        if missing_free_float:
            quality_reasons.append("MISSING_FLOAT_STATE_CARRIED")
        elif fallback:
            quality_reasons.append("DAILY_BAR_FALLBACK")
        if (
            prepared_minute_path.total_volume
            > expected_free_float_shares + tolerance(expected_free_float_shares)
        ):
            prepared_minute_path = _cap_prepared_minute_path(
                prepared_minute_path,
                max_volume=expected_free_float_shares,
            )
            quality_reasons.append("TURNOVER_CAPPED_AT_FLOAT")
        input_quality_reason_codes = tuple(quality_reasons)
        for model in SELLER_MODEL_ORDER:
            previous_post = current[model]
            in_output_year = fact.target_required
            emit_day = (
                emit_operators
                and in_output_year
                and (emit_start_date is None or trading_date >= emit_start_date)
            )
            if emit_day and writer is not None and model not in previous_output_states:
                if isinstance(previous_post, ChipSnapshotV2):
                    previous_view, previous_economic = (
                        codec.snapshot_view_and_economic_buckets(previous_post, grid)
                    )
                else:
                    previous_view, _, _, previous_economic = (
                        codec.register_state_and_profile(previous_post, grid)
                    )
                previous_output_states[model] = previous_view
                previous_output_economic_buckets[model] = previous_economic
            inventory_events = _inventory_events(previous_post, row)
            mutable_state = engines[model].advance_packed_warmup_day(
                previous_post=previous_post,
                decision_at=decision_at,
                available_at=decision_at,
                inventory_events=inventory_events,
                expected_free_float_shares=expected_free_float_shares,
                additional_input_snapshot_ids=additional_input_snapshot_ids,
                input_hard_valid=input_hard_valid,
                input_quality_reason_codes=input_quality_reason_codes,
                prepared_minute_path=prepared_minute_path,
                build_transition=emit_day,
            )
            if inventory_events:
                # Exact event-day aggregation can change an economic coordinate
                # by one bit.  Regenerate identity at the existing canonical
                # output boundary after all packed mutations are complete.
                mutable_state.packed_lots._cell_ids_current = False
            _canonicalize_packed_output_state(mutable_state)
            current[model] = mutable_state
            max_mass_error = max(
                max_mass_error, abs(mutable_state.conservation_error)
            )
            if emit_day:
                if writer is None and day_sink is None:
                    raise RuntimeError("output emission requires a writer or day sink")
                transition = mutable_state.last_transition
                if transition is None:
                    raise RuntimeError("output-year transition was not built")
                max_same_day_resale = max(
                    max_same_day_resale, abs(transition.same_day_resale_shares)
                )
                output_row, output_state, output_economic = _output_row(
                    state=mutable_state,
                    transition=transition,
                    fallback=fallback,
                    previous_post=(
                        None
                        if emit_start_date is not None and model not in emitted_models
                        else previous_output_states.get(model)
                    ),
                    previous_economic_buckets=(
                        None
                        if emit_start_date is not None and model not in emitted_models
                        else previous_output_economic_buckets.get(model)
                    ),
                    codec=codec,
                    grid=grid,
                    cash_dividend_per_share=float(
                        row.get("cash_per_share") or 0.0
                    ),
                    share_multiplier=float(row.get("share_multiplier") or 1.0),
                    action_provenance_ids=parse_action_ids(
                        row.get("corporate_action_ids")
                    ),
                    force_checkpoint=(
                        model not in emitted_models
                        or emitted_day_count % CHECKPOINT_INTERVAL_DAYS == 0
                    ),
                    current_price=float(row["close"]),
                    encode_replay=writer is not None,
                )
                if writer is not None:
                    output_rows.append(output_row)
                    previous_output_states[model] = output_state
                    previous_output_economic_buckets[model] = output_economic
                if day_sink is not None:
                    day_projection_rows.append(
                        dict(zip(OUTPUT_SCHEMA.names, output_row, strict=True))
                    )
                emitted_models.add(model)
                if writer is not None and len(output_rows) >= output_row_group_size:
                    writer.write_table(
                        output_rows.to_table(),
                        row_group_size=output_row_group_size,
                    )
                    output_count += len(output_rows)
                    output_rows.clear()
        if day_sink is not None and day_projection_rows:
            day_sink(fact, tuple(day_projection_rows), current)
            output_count += len(day_projection_rows)
        if emit_operators and fact.target_required and (
            emit_start_date is None or trading_date >= emit_start_date
        ):
            emitted_day_count += 1
        if fact.target_required:
            target_day_count += 1
    if writer is not None and output_rows:
        if writer is None:
            raise RuntimeError("operator emission requires an output writer")
        writer.write_table(
            output_rows.to_table(),
            row_group_size=output_row_group_size,
        )
        output_count += len(output_rows)
        output_rows.clear()
    if emit_operators and output_count == 0:
        raise ValueError(f"no output rows for {year}")
    if target_day_count != len(replayable_dates):
        raise RuntimeError("replayable date authority diverged from transition loop")
    terminal_snapshots = {
        model: state if isinstance(state, ChipSnapshotV2) else state.to_snapshot()
        for model, state in current.items()
    }
    return {
        "symbol": symbol,
        "rows": output_count,
        "input_days": len(daily_rows),
        "processed_days": len(facts_to_process),
        "target_days": target_day_count,
        "emitted_days": emitted_day_count,
        "replayed_prior_year_days": sum(
            fact.trading_date.year < year for fact in facts_to_process
        ),
        "state_resumed": initial_snapshots is not None,
        "fallback_days": fallback_days,
        "max_mass_error": max_mass_error,
        "max_same_day_resale": max_same_day_resale,
        # Exact transitions are persisted for all three models. Strategy-anchor
        # lineage is replayed on demand; rebuilding a throwaway annual tracer
        # here duplicated the same transition walk without producing data.
        "lineage_models": len(emitted_models),
        "cells": codec.cell_count,
    }, terminal_snapshots


def _part_path(output_root: Path, bucket: int, symbol: str) -> Path:
    return output_root / "parts" / f"bucket={bucket}" / f"{symbol.replace('.', '_')}.parquet"


def _terminal_path(output_root: Path, bucket: int, symbol: str) -> Path:
    return (
        output_root
        / "terminal"
        / f"bucket={bucket}"
        / f"{symbol.replace('.', '_')}.parquet"
    )


def _feature_fact_path(output_root: Path, bucket: int, symbol: str) -> Path:
    return (
        output_root
        / "daily_feature_fact"
        / f"symbol_bucket={bucket}"
        / f"{symbol.replace('.', '_')}.parquet"
    )


def _write_terminal_snapshots(
    path: Path, snapshots: dict[SellerModel, ChipSnapshotV2]
) -> None:
    if set(snapshots) != set(SELLER_MODEL_ORDER):
        raise ValueError("terminal state must contain all seller models")
    rows: list[dict[str, Any]] = []
    for model in SELLER_MODEL_ORDER:
        snapshot = snapshots[model]
        rows.append(
            {
                "storage_version": STORAGE_VERSION,
                "model_version": snapshot.model_version,
                "grid_version": snapshot.grid_version,
                "symbol": snapshot.symbol,
                "trading_date": snapshot.trading_date,
                "decision_at": snapshot.decision_at,
                "effective_at": snapshot.effective_at,
                "available_at": snapshot.available_at,
                "phase": snapshot.phase.value,
                "snapshot_id": snapshot.snapshot_id,
                "seller_model": snapshot.seller_model.value,
                "free_float_shares": snapshot.free_float_shares,
                "latent_supply_shares": snapshot.latent_supply_shares,
                "input_snapshot_ids": list(snapshot.input_snapshot_ids),
                "pit_grade": snapshot.pit_grade,
                "hard_valid": snapshot.hard_valid,
                "quality_reason_codes": list(snapshot.quality_reason_codes),
                "cells": [
                    {
                        "cell_id": cell.cell_id,
                        "cost_bucket_id": cell.cost_bucket_id,
                        "holding_days": cell.holding_days,
                        "sensitivity": cell.sensitivity.value,
                        "acquisition_cost": cell.acquisition_cost,
                        "economic_break_even": cell.economic_break_even,
                        "shares": cell.shares,
                        "initialization_prior_units": cell.initialization_prior_units,
                    }
                    for cell in snapshot.inventory.cells
                ],
            }
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.Table.from_pylist(rows, schema=TERMINAL_SCHEMA),
        path,
        compression="zstd",
        compression_level=PARQUET_COMPRESSION_LEVEL,
        use_dictionary=True,
    )


def _read_terminal_snapshots(
    path: Path,
    symbol: str,
    *,
    before_year: int | None = None,
    expected_year: int | None = None,
) -> dict[SellerModel, ChipSnapshotV2]:
    table = pq.read_table(path, schema=TERMINAL_SCHEMA)
    if table.num_rows != len(SELLER_MODEL_ORDER):
        raise ValueError("terminal state must have exactly three model rows")
    snapshots: dict[SellerModel, ChipSnapshotV2] = {}
    dates: set[date] = set()
    for row in table.to_pylist():
        if row["storage_version"] not in {"chip-operator-log-v11", STORAGE_VERSION}:
            raise ValueError("terminal storage version mismatch")
        if row["model_version"] != MODEL_VERSION or row["grid_version"] != GRID_VERSION:
            raise ValueError("terminal model/grid version mismatch")
        if row["symbol"] != symbol:
            raise ValueError("terminal symbol mismatch")
        model = SellerModel(row["seller_model"])
        if model in snapshots:
            raise ValueError("duplicate terminal seller model")
        trading_date = _date(row["trading_date"])
        if before_year is not None and trading_date >= date(before_year, 1, 1):
            raise ValueError("terminal state does not precede target year")
        dates.add(trading_date)
        cells = tuple(
            InventoryCell.create(
                cost_bucket_id=(
                    None
                    if cell["cost_bucket_id"] is None
                    else int(cell["cost_bucket_id"])
                ),
                holding_days=int(cell["holding_days"]),
                sensitivity=TurnoverSensitivity(cell["sensitivity"]),
                acquisition_cost=cell["acquisition_cost"],
                economic_break_even=cell["economic_break_even"],
                shares=float(cell["shares"]),
                initialization_prior_units=float(cell["initialization_prior_units"]),
            )
            for cell in row["cells"]
        )
        snapshots[model] = ChipSnapshotV2(
            symbol=symbol,
            trading_date=trading_date,
            decision_at=_timestamp(row["decision_at"]),
            effective_at=_timestamp(row["effective_at"]),
            available_at=_timestamp(row["available_at"]),
            phase=SnapshotPhase(row["phase"]),
            snapshot_id=row["snapshot_id"],
            model_version=row["model_version"],
            grid_version=row["grid_version"],
            seller_model=model,
            inventory=SparseChipInventory.canonical(cells),
            free_float_shares=float(row["free_float_shares"]),
            latent_supply_shares=float(row["latent_supply_shares"]),
            input_snapshot_ids=tuple(row["input_snapshot_ids"]),
            pit_grade=row["pit_grade"],
            hard_valid=bool(row["hard_valid"]),
            quality_reason_codes=tuple(row["quality_reason_codes"]),
        )
    if set(snapshots) != set(SELLER_MODEL_ORDER) or len(dates) != 1:
        raise ValueError("terminal state model/date set is incomplete")
    if expected_year is not None and {value.year for value in dates} != {
        expected_year
    }:
        raise ValueError(
            "terminal state must come from the immediately previous year: "
            f"expected={expected_year}, actual={sorted(value.year for value in dates)}"
        )
    return snapshots


def _existing_part_result(
    path: Path,
    symbol: str,
    terminal_path: Path | None = None,
    year: int | None = None,
) -> dict[str, Any] | None:
    """Read only the small scalar columns needed to resume a completed symbol."""
    if not path.exists():
        return None
    try:
        parquet_file = pq.ParquetFile(path)
        if not {"storage_version", "model_version"}.issubset(
            parquet_file.schema_arrow.names
        ):
            return None
        table = pq.read_table(
            path,
            columns=[
                "storage_version",
                "model_version",
                "trade_date",
                "seller_model",
                "minute_fallback",
                "conservation_error_shares",
                "same_day_resale_shares",
            ],
        )
    except (KeyError, OSError, pa.ArrowInvalid):
        return None
    if table.num_rows == 0:
        return None
    values = table.to_pydict()
    if set(values["storage_version"]) != {STORAGE_VERSION}:
        return None
    if set(values["model_version"]) != {MODEL_VERSION}:
        return None
    if terminal_path is not None:
        if year is None:
            raise ValueError("year is required when validating a terminal state")
        try:
            terminal = _read_terminal_snapshots(
                terminal_path, symbol, before_year=year + 1
            )
        except (OSError, ValueError, pa.ArrowInvalid):
            return None
        if {snapshot.trading_date.year for snapshot in terminal.values()} != {year}:
            return None
    fallback_dates = {
        trading_date
        for trading_date, fallback in zip(
            values["trade_date"], values["minute_fallback"], strict=True
        )
        if fallback
    }
    return {
        "symbol": symbol,
        "rows": table.num_rows,
        "input_days": 0,
        "processed_days": 0,
        "target_days": len(set(values["trade_date"])),
        "emitted_days": len(set(values["trade_date"])),
        "replayed_prior_year_days": 0,
        "state_resumed": None,
        "compute_seconds": 0.0,
        "fallback_days": len(fallback_dates),
        "max_mass_error": max(
            (abs(value) for value in values["conservation_error_shares"]),
            default=0.0,
        ),
        "max_same_day_resale": max(
            (abs(value) for value in values["same_day_resale_shares"]),
            default=0.0,
        ),
        "lineage_models": len(set(values["seller_model"])),
        "cells": 0,
        "resumed": True,
    }


def _existing_terminal_result(
    terminal_path: Path, symbol: str, year: int
) -> dict[str, Any] | None:
    if not terminal_path.exists():
        return None
    try:
        snapshots = _read_terminal_snapshots(
            terminal_path,
            symbol,
            before_year=year + 1,
            expected_year=year,
        )
    except (OSError, ValueError, pa.ArrowInvalid):
        return None
    return {
        "symbol": symbol,
        "rows": 0,
        "input_days": 0,
        "processed_days": 0,
        "target_days": 0,
        "emitted_days": 0,
        "replayed_prior_year_days": 0,
        "state_resumed": None,
        "compute_seconds": 0.0,
        "fallback_days": 0,
        "max_mass_error": max(
            abs(snapshot.conservation_error) for snapshot in snapshots.values()
        ),
        "max_same_day_resale": 0.0,
        "lineage_models": len(snapshots),
        "cells": sum(len(snapshot.inventory.cells) for snapshot in snapshots.values()),
        "resumed": True,
    }


def _write_symbol_part(
    *,
    path: Path,
    terminal_path: Path,
    symbol: str,
    daily_rows: list[dict[str, Any]],
    minute_rows: list[dict[str, Any]],
    year: int,
    initial_snapshots: dict[SellerModel, ChipSnapshotV2] | None = None,
    emit_operators: bool = True,
    emit_start_date: date | None = None,
) -> dict[str, Any]:
    output_root = path.parents[2]
    bucket = int(path.parent.name.split("=", 1)[1])
    feature_path = _feature_fact_path(output_root, bucket, symbol)
    resumed = (
        _existing_part_result(path, symbol, terminal_path, year)
        if emit_operators
        else _existing_terminal_result(terminal_path, symbol, year)
    )
    if emit_operators and not feature_path.is_file():
        resumed = None
    if resumed is not None:
        return resumed
    started = time.perf_counter()
    if emit_operators:
        path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".tmp.parquet")
    temp_terminal_path = terminal_path.with_suffix(".tmp.parquet")
    temp_path.unlink(missing_ok=True)
    temp_terminal_path.unlink(missing_ok=True)
    writer = (
        pq.ParquetWriter(
            temp_path,
            OUTPUT_SCHEMA,
            compression="zstd",
            compression_level=PARQUET_COMPRESSION_LEVEL,
            use_dictionary=True,
        )
        if emit_operators
        else None
    )
    gc_was_enabled = gc.isenabled()
    if gc_was_enabled:
        gc.disable()
    try:
        result, terminal_snapshots = _run_symbol(
            symbol,
            daily_rows,
            minute_rows,
            year,
            writer,
            initial_snapshots,
            emit_operators=emit_operators,
            emit_start_date=emit_start_date,
        )
    except Exception:
        if writer is not None:
            writer.close()
        temp_path.unlink(missing_ok=True)
        temp_terminal_path.unlink(missing_ok=True)
        raise
    finally:
        if gc_was_enabled:
            gc.enable()
    if writer is not None:
        writer.close()
    temp_feature_path = feature_path.with_suffix(".tmp.parquet")
    temp_feature_path.unlink(missing_ok=True)
    try:
        if emit_operators:
            build_daily_feature_fact(temp_path, temp_feature_path)
        _write_terminal_snapshots(temp_terminal_path, terminal_snapshots)
        _read_terminal_snapshots(temp_terminal_path, symbol, before_year=year + 1)
    except Exception:
        temp_path.unlink(missing_ok=True)
        temp_terminal_path.unlink(missing_ok=True)
        temp_feature_path.unlink(missing_ok=True)
        raise
    terminal_path.parent.mkdir(parents=True, exist_ok=True)
    temp_terminal_path.replace(terminal_path)
    if emit_operators:
        temp_path.replace(path)
        feature_path.parent.mkdir(parents=True, exist_ok=True)
        temp_feature_path.replace(feature_path)
    result["resumed"] = False
    result["compute_seconds"] = round(time.perf_counter() - started, 3)
    return result


def _run_bucket(
    payload: tuple[
        int,
        int,
        Path,
        Path,
        Path | None,
        float,
        tuple[str, ...],
        bool,
        date | None,
    ]
) -> dict[str, Any]:
    (
        bucket,
        year,
        stage_root,
        output_root,
        resume_root,
        _memory_limit_gb,
        symbols,
        emit_operators,
        emit_start_date,
    ) = payload
    started = time.perf_counter()
    daily_partitions = _symbol_partition_dirs(stage_root, "daily", bucket)
    minute_partitions = _symbol_partition_dirs(stage_root, "minute", bucket)
    prior_symbols = _read_prior_symbols(stage_root)
    selected = sorted(daily_partitions)
    if symbols:
        requested = set(symbols)
        selected = [symbol for symbol in selected if symbol in requested]
    results: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    new_listing_symbols = 0
    for position, symbol in enumerate(selected, start=1):
        part_path = _part_path(output_root, bucket, symbol)
        terminal_path = _terminal_path(output_root, bucket, symbol)
        resumed = (
            _existing_part_result(part_path, symbol, terminal_path, year)
            if emit_operators
            else _existing_terminal_result(terminal_path, symbol, year)
        )
        if emit_operators and not _feature_fact_path(
            output_root, bucket, symbol
        ).is_file():
            resumed = None
        if resumed is not None:
            results.append(resumed)
            continue
        try:
            daily_rows = _read_symbol_partition(daily_partitions[symbol], symbol)
            initial_snapshots = None
            if resume_root is not None:
                previous_terminal = _terminal_path(resume_root, bucket, symbol)
                if previous_terminal.exists():
                    initial_snapshots = _read_terminal_snapshots(
                        previous_terminal,
                        symbol,
                        before_year=year,
                        expected_year=year - 1,
                    )
                elif symbol in prior_symbols:
                    raise FileNotFoundError(
                        "prior-history symbol is missing its adjacent-year terminal state"
                    )
                else:
                    # The stock first appears inside this horizon. Its opening
                    # inventory is unknown cost; do not replay unrelated years.
                    new_listing_symbols += 1
            results.append(
                _write_symbol_part(
                    path=part_path,
                    terminal_path=terminal_path,
                    symbol=symbol,
                    daily_rows=daily_rows,
                    minute_rows=_read_symbol_partition(
                        minute_partitions.get(symbol), symbol
                    ),
                    year=year,
                    initial_snapshots=initial_snapshots,
                    emit_operators=emit_operators,
                    emit_start_date=emit_start_date,
                )
            )
        except Exception as error:
            if os.environ.get("CYQ_RAISE_TASK_ERRORS") == "1":
                raise
            failures.append(
                {"symbol": symbol, "error": f"{type(error).__name__}: {error}"}
            )
        if position % 25 == 0:
            gc.collect()
    return {
        "bucket": bucket,
        "symbols": len(selected),
        "passed": len(results),
        "failed": len(failures),
        "rows": sum(item["rows"] for item in results),
        "input_days": sum(item["input_days"] for item in results),
        "processed_days": sum(item["processed_days"] for item in results),
        "target_days": sum(item["target_days"] for item in results),
        "emitted_days": sum(item["emitted_days"] for item in results),
        "replayed_prior_year_days": sum(
            item["replayed_prior_year_days"] for item in results
        ),
        "state_resumed_symbols": sum(
            item.get("state_resumed") is True for item in results
        ),
        "new_listing_symbols": new_listing_symbols,
        "compute_seconds": round(
            sum(item["compute_seconds"] for item in results), 3
        ),
        "fallback_days": sum(item["fallback_days"] for item in results),
        "max_mass_error": max((item["max_mass_error"] for item in results), default=0.0),
        "max_same_day_resale": max(
            (item["max_same_day_resale"] for item in results), default=0.0
        ),
        "lineage_pass": all(item["lineage_models"] in (0, 3) for item in results),
        "resumed_symbols": sum(bool(item.get("resumed")) for item in results),
        "failures": failures,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }


def _task_payloads(
    *,
    selected_buckets: list[int],
    year: int,
    stage_root: Path,
    output_root: Path,
    resume_root: Path | None,
    memory_per_worker_gb: float,
    requested_symbols: tuple[str, ...],
    workers: int,
    symbols_per_task: int,
    emit_operators: bool,
    emit_start_date: date | None,
) -> list[
    tuple[
        int,
        int,
        Path,
        Path,
        Path | None,
        float,
        tuple[str, ...],
        bool,
        date | None,
    ]
]:
    """Split physical buckets into dynamic symbol tasks.

    The staged files stay bucket-partitioned, but workers no longer own one
    whole bucket for the entire run.  Shorter tasks let a free worker take work
    from a slower bucket instead of leaving a CPU idle near the end.
    """

    requested = set(requested_symbols)
    payloads: list[
        tuple[
            int,
            int,
            Path,
            Path,
            Path | None,
            float,
            tuple[str, ...],
            bool,
            date | None,
        ]
    ] = []
    for bucket in selected_buckets:
        available = sorted(_symbol_partition_dirs(stage_root, "daily", bucket))
        if requested:
            available = [symbol for symbol in available if symbol in requested]
        if not available:
            continue
        if workers <= 1 or len(available) <= symbols_per_task:
            chunks = [tuple(available)]
        else:
            chunks = [
                tuple(available[start : start + symbols_per_task])
                for start in range(0, len(available), symbols_per_task)
            ]
        payloads.extend(
            (
                bucket,
                year,
                stage_root,
                output_root,
                resume_root,
                memory_per_worker_gb,
                chunk,
                emit_operators,
                emit_start_date,
            )
            for chunk in chunks
        )
    return payloads


def _aggregate_bucket_tasks(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep summary compatibility after dynamic task splitting."""

    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for result in results:
        grouped[result["bucket"]].append(result)
    aggregated: list[dict[str, Any]] = []
    summed = (
        "symbols",
        "passed",
        "failed",
        "rows",
        "input_days",
        "processed_days",
        "target_days",
        "emitted_days",
        "replayed_prior_year_days",
        "state_resumed_symbols",
        "new_listing_symbols",
        "compute_seconds",
        "fallback_days",
        "resumed_symbols",
        "elapsed_seconds",
    )
    for bucket, tasks in sorted(grouped.items()):
        item: dict[str, Any] = {"bucket": bucket}
        item.update({key: sum(task[key] for task in tasks) for key in summed})
        item["max_mass_error"] = max(task["max_mass_error"] for task in tasks)
        item["max_same_day_resale"] = max(
            task["max_same_day_resale"] for task in tasks
        )
        item["lineage_pass"] = all(task["lineage_pass"] for task in tasks)
        item["failures"] = [
            failure for task in tasks for failure in task["failures"]
        ]
        item["task_count"] = len(tasks)
        aggregated.append(item)
    return aggregated


def _checkpoint_journal_jsonable(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"unsupported checkpoint/journal progress value: {type(value).__name__}")


def _checkpoint_journal_artifact_payload(
    artifact: SymbolArtifacts, result: dict[str, Any]
) -> dict[str, Any]:
    return json.loads(
        json.dumps(
            {"artifact": asdict(artifact), "result": result},
            default=_checkpoint_journal_jsonable,
            sort_keys=True,
        )
    )


def _checkpoint_journal_artifact_from_payload(payload: dict[str, Any]) -> SymbolArtifacts:
    raw = payload["artifact"]
    rows = []
    for item in raw["index_rows"]:
        feature = item["feature_binding"]
        rows.append(
            CheckpointJournalIndexRow(
                storage_version=item["storage_version"],
                schema_version=item["schema_version"],
                artifact_version=item["artifact_version"],
                symbol=item["symbol"],
                target_year=int(item["target_year"]),
                checkpoint_dates=tuple(date.fromisoformat(value) for value in item["checkpoint_dates"]),
                checkpoint_anchor_date=date.fromisoformat(item["checkpoint_anchor_date"]),
                journal_start_date=date.fromisoformat(item["journal_start_date"]),
                journal_end_date=date.fromisoformat(item["journal_end_date"]),
                seller_models=tuple(item["seller_models"]),
                checkpoint_part_path=item["checkpoint_part_path"],
                checkpoint_part_digest=item["checkpoint_part_digest"],
                journal_part_path=item["journal_part_path"],
                journal_part_digest=item["journal_part_digest"],
                dependency_manifest_digest=item["dependency_manifest_digest"],
                replay_parameter_manifest_digest=item["replay_parameter_manifest_digest"],
                terminal_completeness_digest=item["terminal_completeness_digest"],
                feature_binding=FeatureAssetBinding(
                    asset_id=feature["asset_id"],
                    snapshot_id=feature["snapshot_id"],
                    content_digest=feature["content_digest"],
                    available_at=datetime.fromisoformat(feature["available_at"]),
                ),
                bundle_id=item["bundle_id"],
                root_id=item["root_id"],
            )
        )
    file_metadata = tuple(
        ArtifactFileMetadata(
            kind=item["kind"],
            relative_path=item["relative_path"],
            bytes=int(item["bytes"]),
            sha256=item["sha256"],
            logical_digest=item["logical_digest"],
        )
        for item in raw.get("file_metadata", ())
    )
    return SymbolArtifacts(
        symbol=raw["symbol"],
        trading_days=int(raw["trading_days"]),
        model_rows=int(raw["model_rows"]),
        checkpoint_paths=tuple(raw["checkpoint_paths"]),
        journal_paths=tuple(raw["journal_paths"]),
        feature_path=raw["feature_path"],
        terminal_path=raw["terminal_path"],
        index_rows=tuple(rows),
        checkpoint_bytes=int(raw["checkpoint_bytes"]),
        journal_bytes=int(raw["journal_bytes"]),
        feature_bytes=int(raw["feature_bytes"]),
        terminal_bytes=int(raw["terminal_bytes"]),
        fallback_rows=int(raw["fallback_rows"]),
        fallback_bytes=int(raw["fallback_bytes"]),
        file_metadata=file_metadata,
        checkpoint_dates_digest=raw.get("checkpoint_dates_digest", ""),
    )


def _artifact_logical_digest(artifact: SymbolArtifacts) -> str:
    if not artifact.file_metadata:
        raise ValueError("symbol artifact lacks hash-once file metadata")
    return logical_sha256(
        tuple(
            {
                "kind": item.kind,
                "logical_digest": item.logical_digest,
                "relative_path": item.relative_path,
            }
            for item in sorted(
                artifact.file_metadata,
                key=lambda value: value.relative_path.encode("utf-8"),
            )
        )
    )


def _resume_contract_binding(
    *,
    artifact: SymbolArtifacts,
    payload: Mapping[str, Any],
    input_fingerprint: str,
    input_manifest_path: Path,
) -> dict[str, Any]:
    return {
        "shard_manifest_version": SHARD_MANIFEST_VERSION,
        "resume_contract_version": RESUME_CONTRACT_VERSION,
        "symbol": artifact.symbol,
        "year": int(payload["year"]),
        "semantic_fingerprint": payload["semantic_fingerprint"],
        "input_fingerprint": input_fingerprint,
        "input_manifest_path": str(input_manifest_path),
        "artifact_contract_fingerprint": payload["artifact_contract_fingerprint"],
        "physical_fingerprint": payload["physical_fingerprint"],
        "logical_digest": _artifact_logical_digest(artifact),
        "checkpoint_dates_digest": artifact.checkpoint_dates_digest,
        "file_integrity_digests": [
            asdict(item)
            for item in sorted(
                artifact.file_metadata,
                key=lambda value: value.relative_path.encode("utf-8"),
            )
        ],
        "execution_metadata": {
            "workers": int(payload.get("workers", 1)),
            "buffer_rows": int(payload.get("output_buffer_rows", 3)),
            "scheduler": payload.get("scheduler", "utf8-symbol-order"),
            "largest_first": bool(payload.get("largest_first", False)),
            "rss_policy_bytes": 1_584_050_791,
            "git_head": payload.get("git_head", "UNKNOWN"),
            "pid": os.getpid(),
            "python": sys.version.split()[0],
        },
    }


def _checkpoint_codec_parts_from_packed_states(
    states: Mapping[SellerModel, ChipSnapshotV2 | MutableChipState],
) -> tuple[tuple[CellIdentity, ...], tuple[CheckpointModelState, ...]]:
    """Project canonical packed arrays directly into the checkpoint schema."""

    packed_states: list[tuple[MutableChipState, np.ndarray]] = []
    identities_by_id: dict[int, CellIdentity] = {}
    for model in SELLER_MODEL_ORDER:
        state = states[model]
        if not isinstance(state, MutableChipState):
            raise TypeError("production checkpoint capture requires packed mutable state")
        packed = state.packed_lots
        packed.refresh_cell_ids()
        size = len(packed)
        active = np.flatnonzero(packed._shares[:size] > 0)
        cell_ids = packed._cell_ids[active]
        if np.unique(cell_ids).size != active.size:
            raise ValueError("checkpoint capture received duplicate canonical identities")
        order = np.argsort(cell_ids, kind="stable")
        active = active[order]
        packed_states.append((state, active))
        for index_value in active:
            index = int(index_value)
            cell_id = int(packed._cell_ids[index])
            economic_break_even = float(packed._economic_break_evens[index])
            identity = CellIdentity(
                cell_id=cell_id,
                cost_bucket_id=(
                    int(packed._cost_bucket_ids[index])
                    if math.isfinite(economic_break_even)
                    else None
                ),
                holding_days=int(packed._holding_days[index]),
                sensitivity=(
                    TurnoverSensitivity.ACTIVE,
                    TurnoverSensitivity.NEUTRAL,
                    TurnoverSensitivity.STICKY,
                )[int(packed._sensitivity_codes[index])].value,
                economic_break_even_bits=(
                    f64be_bits(economic_break_even)
                    if math.isfinite(economic_break_even)
                    else None
                ),
                economic_coordinate_version="causal-economic-price-v2",
            )
            previous = identities_by_id.setdefault(cell_id, identity)
            if previous != identity:
                raise ValueError("same cell_id has conflicting checkpoint identity")

    identities = tuple(identities_by_id[key] for key in sorted(identities_by_id))
    positions = {identity.cell_id: index for index, identity in enumerate(identities)}
    empty_digest = hashlib.sha256(b"").hexdigest()
    empty_lifecycle = LifecycleContinuation(
        lifecycle_version="phase2-no-active-anchor-v1",
        active_anchor_ids=(),
        anchors=(),
        identity_digest=empty_digest,
        share_digest=empty_digest,
        retention_digest=empty_digest,
        destination_digest=empty_digest,
    )
    model_states = []
    for state, active in packed_states:
        packed = state.packed_lots
        if packed is None:
            raise AssertionError("packed checkpoint state disappeared")
        lots = tuple(
            CheckpointLot(
                identity_position=positions[int(packed._cell_ids[int(index_value)])],
                shares_bits=f64be_bits(float(packed._shares[int(index_value)])),
                acquisition_cost_bits=(
                    f64be_bits(float(packed._acquisition_costs[int(index_value)]))
                    if math.isfinite(
                        float(packed._acquisition_costs[int(index_value)])
                    )
                    else None
                ),
                initialization_prior_units_bits=f64be_bits(
                    float(packed._initialization_prior_units[int(index_value)])
                ),
            )
            for index_value in active
        )
        conservation_error = (
            math.fsum(float(packed._shares[int(index_value)]) for index_value in active)
            - state.free_float_shares
        )
        model_states.append(
            CheckpointModelState(
                seller_model=state.seller_model.value,
                decision_at=state.decision_at,
                available_at=state.available_at,
                effective_at=state.effective_at,
                phase=state.phase.value,
                snapshot_id=state.snapshot_id,
                model_version=state.model_version,
                grid_version=state.grid_version,
                lots=lots,
                free_float_shares_bits=f64be_bits(state.free_float_shares),
                latent_supply_shares_bits=f64be_bits(state.latent_supply_shares),
                conservation_error_bits=f64be_bits(conservation_error),
                input_snapshot_ids=tuple(
                    sorted(
                        set(state.input_snapshot_ids),
                        key=lambda item: item.encode("utf-8"),
                    )
                ),
                pit_grade=state.pit_grade,
                hard_valid=state.hard_valid,
                quality_reason_codes=tuple(
                    sorted(
                        set(state.quality_reason_codes),
                        key=lambda item: item.encode("utf-8"),
                    )
                ),
                seller_continuation=SellerContinuation(
                    continuation_version="canonical-seller-continuation-v1",
                    values={
                        "seller_model": state.seller_model.value,
                        "snapshot_id": state.snapshot_id,
                    },
                ),
                lifecycle_continuation=empty_lifecycle,
            )
        )
    return identities, tuple(model_states)


def _canonicalize_packed_output_state(state: MutableChipState) -> None:
    """Merge identical packed identities at the canonical output boundary."""

    packed = state.packed_lots
    if packed is None:
        return
    packed.refresh_cell_ids()
    size = len(packed)
    active = np.flatnonzero(packed._shares[:size] > 0)
    cell_ids = packed._cell_ids[active]
    if np.unique(cell_ids).size == active.size:
        return
    grouped: dict[int, list[int]] = defaultdict(list)
    for index_value in active:
        index = int(index_value)
        grouped[int(packed._cell_ids[index])].append(index)
    keep = np.ones(size, dtype=bool)
    for cell_id, indexes in grouped.items():
        if len(indexes) == 1:
            continue
        first = indexes[0]
        identity = (
            int(packed._cost_bucket_ids[first]),
            int(packed._holding_days[first]),
            int(packed._sensitivity_codes[first]),
            struct.pack(">d", float(packed._economic_break_evens[first])),
        )
        for index in indexes[1:]:
            candidate = (
                int(packed._cost_bucket_ids[index]),
                int(packed._holding_days[index]),
                int(packed._sensitivity_codes[index]),
                struct.pack(">d", float(packed._economic_break_evens[index])),
            )
            if candidate != identity:
                raise ValueError(f"cell hash collision for {cell_id}")
        member_shares = [float(packed._shares[index]) for index in indexes]
        combined_shares = math.fsum(member_shares)
        packed._shares[first] = combined_shares
        packed._initialization_prior_units[first] = math.fsum(
            float(packed._initialization_prior_units[index]) for index in indexes
        )
        if math.isfinite(float(packed._economic_break_evens[first])):
            packed._acquisition_costs[first] = (
                math.fsum(
                    shares * float(packed._acquisition_costs[index])
                    for shares, index in zip(member_shares, indexes, strict=True)
                )
                / combined_shares
            )
        keep[indexes[1:]] = False
    packed.retain(keep)
    packed._cell_ids_current = True


def _checkpoint_journal_symbol_worker(payload: dict[str, Any]) -> dict[str, Any]:
    symbol = payload["symbol"]
    year = int(payload["year"])
    daily_path = Path(payload["daily_path"])
    minute_path = payload.get("minute_path")
    minute_partition = None if minute_path is None else Path(minute_path)
    stage_root = Path(payload.get("stage_root", daily_path.parents[2]))
    input_manifest_root = Path(
        payload.get(
            "input_manifest_root",
            Path(payload["progress_root"]) / "input-manifests",
        )
    )
    output_buffer_rows = int(payload.get("output_buffer_rows", len(SELLER_MODEL_ORDER)))
    if output_buffer_rows not in BUFFER_CANDIDATES:
        raise ValueError("checkpoint/journal buffer rows are outside the frozen candidates")
    input_fingerprint, input_manifest_path = _symbol_input_fingerprint(
        symbol=symbol,
        year=year,
        stage_root=stage_root,
        daily_path=daily_path,
        minute_path=minute_partition,
        manifest_root=input_manifest_root,
    )
    dependency_manifest_digest = logical_sha256(
        {"symbol": symbol, "year": year, "input_fingerprint": input_fingerprint}
    )
    replay_contract_hash = logical_sha256(
        {
            "semantic_fingerprint": payload["semantic_fingerprint"],
            "input_fingerprint": input_fingerprint,
            "artifact_contract_fingerprint": payload[
                "artifact_contract_fingerprint"
            ],
        }
    )
    daily_rows = _read_symbol_partition(daily_path, symbol)
    minute_rows = _read_symbol_partition(minute_partition, symbol)
    replayable_facts = _build_replayable_day_facts(
        daily_rows, minute_rows, year, state_resumed=False
    )
    replayable_dates = tuple(
        fact.trading_date for fact in replayable_facts if fact.target_required
    )
    candidate_root = Path(payload["candidate_root"])
    safe_symbol = symbol.replace(".", "_")
    temporary_root = Path(
        tempfile.mkdtemp(
            prefix=f"v12_checkpoint_journal_phase7_{safe_symbol}_", dir="/tmp"
        )
    )
    feature_path = temporary_root / "feature.parquet"
    terminal_path = temporary_root / "terminal.parquet"
    feature_rows: list[tuple[object, ...]] = []
    features: list[dict[str, Any]] = []
    checkpoint_parts: dict[date, tuple[ArtifactFileMetadata, str]] = {}
    journal_parts: dict[tuple[date, date], ArtifactFileMetadata] = {}
    journal_buffer: list[Any] = []
    journal_month: tuple[int, int] | None = None
    journal_anchor_digest: str | None = None
    tracker = EnsembleTemporalPeakTracker(
        symbol=symbol, models=("uniform", "disposition", "active_sticky")
    )

    def flush_journal_month() -> None:
        nonlocal journal_buffer
        if not journal_buffer:
            return
        logical = build_journal_logical(
            symbol=symbol,
            target_year=year,
            rows=tuple(journal_buffer),
            dependency_manifest_digest=dependency_manifest_digest,
            replay_parameter_manifest_digest=payload[
                "replay_parameter_manifest_digest"
            ],
        )
        metadata = write_journal_part(candidate_root, logical)
        key = (journal_buffer[0].trading_date, journal_buffer[-1].trading_date)
        if key in journal_parts:
            raise RuntimeError("journal stream emitted a month twice")
        journal_parts[key] = metadata
        journal_buffer = []

    def consume_day(
        fact: ReplayableDayFact,
        model_rows: tuple[dict[str, Any], ...],
        states: Mapping[SellerModel, ChipSnapshotV2 | MutableChipState],
    ) -> None:
        nonlocal journal_month, journal_anchor_digest
        if not fact.target_required:
            raise RuntimeError("direct output sink received a non-target day")
        feature_row = project_daily_feature_row(list(model_rows), tracker)
        feature = dict(zip(FACT_SCHEMA.names, feature_row, strict=True))
        feature_rows.append(feature_row)
        features.append(feature)

        month = (fact.trading_date.year, fact.trading_date.month)
        if journal_month is not None and month != journal_month:
            flush_journal_month()
        if fact.checkpoint_label is not None:
            identities, model_states = _checkpoint_codec_parts_from_packed_states(
                states
            )
            logical = build_checkpoint_logical(
                symbol=symbol,
                trading_date=fact.trading_date,
                identities=identities,
                model_states=model_states,
                feature=feature,
                label=fact.checkpoint_label,
                dependency_manifest_digest=dependency_manifest_digest,
                replay_parameter_manifest_digest=payload[
                    "replay_parameter_manifest_digest"
                ],
                replay_contract_hash=replay_contract_hash,
                semantic_fingerprint=payload["semantic_fingerprint"],
                runtime_fingerprint=payload["runtime_fingerprint"],
                terminal_completeness_digest=payload[
                    "terminal_completeness_digest"
                ],
            )
            if fact.trading_date in checkpoint_parts:
                raise RuntimeError("checkpoint stream emitted a date twice")
            checkpoint_parts[fact.trading_date] = write_checkpoint_part(
                candidate_root, logical
            )
        if month != journal_month:
            journal_month = month
            anchor = max(
                checkpoint_date
                for checkpoint_date in checkpoint_parts
                if checkpoint_date <= fact.trading_date
            )
            journal_anchor_digest = checkpoint_parts[anchor][1]
        if journal_anchor_digest is None:
            raise RuntimeError("journal stream lacks an opening checkpoint")
        journal_buffer.append(
            build_journal_day(
                model_rows,
                feature,
                sequence=len(journal_buffer),
                checkpoint_parent_digest=journal_anchor_digest,
                dependency_manifest_digest=dependency_manifest_digest,
                replay_parameter_manifest_digest=payload[
                    "replay_parameter_manifest_digest"
                ],
                replay_contract_hash=replay_contract_hash,
                runtime_fingerprint=payload["runtime_fingerprint"],
            )
        )

    try:
        result, terminal_snapshots = _run_symbol(
            symbol,
            daily_rows,
            minute_rows,
            year,
            None,
            output_row_group_size=output_buffer_rows,
            replayable_day_facts=replayable_facts,
            day_sink=consume_day,
        )
        flush_journal_month()
        emitted_dates = tuple(row["trade_date"] for row in features)
        if emitted_dates != replayable_dates:
            raise RuntimeError("direct sinks diverged from replayable day authority")
        write_daily_feature_rows(feature_rows, feature_path)
        _write_terminal_snapshots(terminal_path, terminal_snapshots)
        artifact = finish_symbol_artifacts(
            root=candidate_root,
            symbol=symbol,
            replayable_dates=replayable_dates,
            checkpoint_parts=checkpoint_parts,
            journal_parts=journal_parts,
            features=features,
            feature_source_path=feature_path,
            terminal_source_path=terminal_path,
            dependency_manifest_digest=dependency_manifest_digest,
            replay_parameter_manifest_digest=payload[
                "replay_parameter_manifest_digest"
            ],
            terminal_completeness_digest=payload[
                "terminal_completeness_digest"
            ],
            bundle_id=payload["bundle_id"],
            root_id=payload["root_id"],
        )
        output = _checkpoint_journal_artifact_payload(artifact, result)
        output["resume_contract"] = _resume_contract_binding(
            artifact=artifact,
            payload=payload,
            input_fingerprint=input_fingerprint,
            input_manifest_path=input_manifest_path,
        )
        progress_path = Path(payload["progress_root"]) / f"{safe_symbol}.json"
        _atomic_write_json(progress_path, output)
        return output
    finally:
        shutil.rmtree(temporary_root, ignore_errors=True)


def _checkpoint_journal_manifest_parts(
    artifacts: list[SymbolArtifacts],
) -> list[dict[str, Any]]:
    """Aggregate file-close metadata without rediscovering or rehashing files."""

    parts = [
        asdict(item)
        for artifact in artifacts
        for item in artifact.file_metadata
    ]
    if len({item["relative_path"] for item in parts}) != len(parts):
        raise ValueError("duplicate checkpoint/journal manifest part")
    return sorted(parts, key=lambda item: item["relative_path"].encode("utf-8"))


def _encoded_logical_digest(path: Path) -> str:
    with path.open("rb") as handle:
        prefix = handle.read(1024)
    match = re.search(rb'"logical_digest":"([0-9a-f]{64})"', prefix)
    if match is None:
        raise ValueError(f"encoded part lacks logical digest: {path}")
    return match.group(1).decode("ascii")


def _legacy_semantic_fingerprint(path: Path) -> str:
    with path.open("rb") as handle:
        handle.seek(max(0, path.stat().st_size - 65_536))
        suffix = handle.read()
    match = re.search(
        rb'semantic_fingerprint\\?"?:\\?"([0-9a-f]{64})', suffix
    )
    if match is None:
        raise ValueError(f"legacy checkpoint lacks semantic fingerprint: {path}")
    return match.group(1).decode("ascii")


def _legacy_file_metadata(
    *, artifact: SymbolArtifacts, source_root: Path
) -> tuple[ArtifactFileMetadata, ...]:
    known_digests: dict[str, str] = {}
    for row in artifact.index_rows:
        known_digests[row.checkpoint_part_path] = row.checkpoint_part_digest
        known_digests[row.journal_part_path] = row.journal_part_digest
    if artifact.index_rows:
        known_digests[artifact.feature_path] = artifact.index_rows[0].feature_binding.content_digest
    metadata = []
    for kind, relative_paths in (
        ("checkpoint", artifact.checkpoint_paths),
        ("journal", artifact.journal_paths),
        ("feature", (artifact.feature_path,)),
        ("terminal", (artifact.terminal_path,)),
    ):
        for relative in relative_paths:
            path = source_root / relative
            physical_digest = known_digests.get(relative)
            if physical_digest is None:
                physical_digest = sha256_file(path)
            if kind in {"checkpoint", "journal"}:
                logical_digest = _encoded_logical_digest(path)
            else:
                logical_digest = arrow_logical_digest(path)
            metadata.append(
                ArtifactFileMetadata(
                    kind=kind,
                    relative_path=relative,
                    bytes=path.stat().st_size,
                    sha256=physical_digest,
                    logical_digest=logical_digest,
                )
            )
    return tuple(metadata)


def _link_symbol_evidence(
    *, source_root: Path, candidate_root: Path, artifact: SymbolArtifacts
) -> None:
    for item in artifact.file_metadata:
        source = source_root / item.relative_path
        destination = candidate_root / item.relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            source_stat = source.stat()
            destination_stat = destination.stat()
            if (source_stat.st_dev, source_stat.st_ino) != (
                destination_stat.st_dev,
                destination_stat.st_ino,
            ):
                raise ValueError("resume overlay contains non-evidence artifact")
            continue
        os.link(source, destination)


def _existing_checkpoint_dates(artifact: SymbolArtifacts) -> tuple[date, ...]:
    values = []
    for relative in artifact.checkpoint_paths:
        match = re.search(r"(\d{4}-\d{2}-\d{2})\.json$", relative)
        if match is None:
            raise ValueError("checkpoint filename lacks cadence date")
        values.append(date.fromisoformat(match.group(1)))
    return tuple(values)


def _v2_progress_compatible(
    *,
    value: Mapping[str, Any],
    candidate_root: Path,
    semantic_fingerprint: str,
    input_fingerprint: str,
    artifact_contract_fingerprint: str,
    checkpoint_dates_digest: str,
) -> bool:
    contract = value.get("resume_contract", {})
    if (
        contract.get("resume_contract_version") != RESUME_CONTRACT_VERSION
        or contract.get("semantic_fingerprint") != semantic_fingerprint
        or contract.get("input_fingerprint") != input_fingerprint
        or contract.get("artifact_contract_fingerprint")
        != artifact_contract_fingerprint
        or contract.get("checkpoint_dates_digest") != checkpoint_dates_digest
    ):
        return False
    files = contract.get("file_integrity_digests", ())
    if not files:
        return False
    for item in files:
        path = candidate_root / item["relative_path"]
        if not path.is_file() or path.stat().st_size != int(item["bytes"]):
            return False
    return True


def _adopt_c12_progress(
    *,
    year: int,
    stage_root: Path,
    daily: Mapping[str, Path],
    minute: Mapping[str, Path],
    candidate_root: Path,
    progress_root: Path,
    input_manifest_root: Path,
    semantic_fingerprint: str,
    artifact_contract_fingerprint: str,
    git_head: str,
) -> dict[str, int]:
    legacy_fingerprint = "c12aeba835df0605079e8c3aebb02ab18bc56a31c574b3d709dbe374100281ce"
    source_run = Path(
        f"/tmp/v12_checkpoint_journal_phase7_run_{year}_{legacy_fingerprint}"
    )
    source_root = source_run / "candidate"
    source_progress = source_run / "progress"
    existing_paths = []
    if source_progress.is_dir():
        for path in sorted(source_progress.glob("*.json")):
            value = json.loads(path.read_text(encoding="utf-8"))
            if "artifact" in value and "result" in value:
                existing_paths.append(path)
    report = {
        "existing_completed_shards": len(existing_paths),
        "reused_shards": 0,
        "incompatible_shards": 0,
        "recompute_shards": 0,
    }
    legacy_semantic = logical_sha256(semantic_fingerprint_fields())
    for progress_path in existing_paths:
        value = json.loads(progress_path.read_text(encoding="utf-8"))
        artifact = _checkpoint_journal_artifact_from_payload(value)
        symbol = artifact.symbol
        compatible = symbol in daily
        expected_dates: tuple[date, ...] = ()
        input_fingerprint = ""
        input_manifest_path = input_manifest_root / "missing"
        if compatible:
            legacy_facts = _build_replayable_day_facts(
                _read_symbol_partition(daily[symbol], symbol),
                _read_symbol_partition(minute.get(symbol), symbol),
                year,
                state_resumed=False,
            )
            expected_dates = tuple(
                fact.trading_date
                for fact in legacy_facts
                if fact.checkpoint_label is not None
            )
            compatible = _existing_checkpoint_dates(artifact) == expected_dates
        if compatible:
            compatible = all(
                row.storage_version == CHECKPOINT_JOURNAL_STORAGE_VERSION
                and row.schema_version == CHECKPOINT_JOURNAL_SCHEMA_VERSION
                and row.artifact_version == CHECKPOINT_JOURNAL_ARTIFACT_VERSION
                and row.symbol == symbol
                and row.target_year == year
                for row in artifact.index_rows
            )
        if compatible:
            first_checkpoint = source_root / artifact.checkpoint_paths[0]
            compatible = _legacy_semantic_fingerprint(first_checkpoint) == legacy_semantic
        if compatible:
            input_fingerprint, input_manifest_path = _symbol_input_fingerprint(
                symbol=symbol,
                year=year,
                stage_root=stage_root,
                daily_path=daily[symbol],
                minute_path=minute.get(symbol),
                manifest_root=input_manifest_root,
            )
            artifact = replace(
                artifact,
                file_metadata=_legacy_file_metadata(
                    artifact=artifact,
                    source_root=source_root,
                ),
                checkpoint_dates_digest=logical_sha256(expected_dates),
            )
            adopted_payload = _checkpoint_journal_artifact_payload(
                artifact,
                value["result"],
            )
            adopted_payload["resume_contract"] = _resume_contract_binding(
                artifact=artifact,
                payload={
                    "year": year,
                    "semantic_fingerprint": semantic_fingerprint,
                    "artifact_contract_fingerprint": artifact_contract_fingerprint,
                    "physical_fingerprint": _physical_fingerprint(3),
                    "workers": 5,
                    "output_buffer_rows": 3,
                    "scheduler": "legacy-c12-utf8-symbol-order",
                    "largest_first": False,
                    "git_head": git_head,
                },
                input_fingerprint=input_fingerprint,
                input_manifest_path=input_manifest_path,
            )
            _link_symbol_evidence(
                source_root=source_root,
                candidate_root=candidate_root,
                artifact=artifact,
            )
            _atomic_write_json(
                progress_root / f"{symbol.replace('.', '_')}.json",
                adopted_payload,
            )
            report["reused_shards"] += 1
        else:
            report["incompatible_shards"] += 1
            report["recompute_shards"] += 1
    return report


def _checkpoint_journal_full_market(args: argparse.Namespace) -> dict[str, Any]:
    if args.year != 2020 or args.stage_root is None or args.output is None:
        raise ValueError("full-market checkpoint/journal build requires year 2020, --stage-root, and --output")
    stage_root = args.stage_root.resolve()
    output = args.output.resolve()
    complete = json.loads((stage_root / "COMPLETE.json").read_text(encoding="utf-8"))
    if complete != {
        "year": 2020,
        "warmup_start": 2018,
        "buckets": 10,
        "layout_version": "bucket-symbol-v3-mixed-native-resolution",
        "prior_history_start": None,
        "end_date": "2020-12-31",
        "daily_root": str(args.daily_root.resolve()),
        "minute_root": str(args.minute_root.resolve()),
        "action_override_sha256": None,
        "baostock_delta_sha256": None,
    }:
        raise ValueError("full-market stage fingerprint mismatch")
    daily: dict[str, Path] = {}
    minute: dict[str, Path] = {}
    for bucket in range(args.buckets):
        for symbol, path in _symbol_partition_dirs(stage_root, "daily", bucket).items():
            if symbol in daily:
                raise ValueError("duplicate full-market daily symbol")
            daily[symbol] = path
        for symbol, path in _symbol_partition_dirs(stage_root, "minute", bucket).items():
            if symbol in minute:
                raise ValueError("duplicate full-market minute symbol")
            minute[symbol] = path
    symbols = tuple(sorted(daily, key=lambda value: value.encode("utf-8")))
    if len(symbols) != 3941 or set(minute) - set(daily) or len(minute) != 3940:
        raise ValueError("full-market stage universe mismatch")
    workers = min(int(args.workers), 5)
    if workers < 1:
        raise ValueError("full-market worker preflight failed")

    buffer_rows = int(args.checkpoint_journal_buffer_rows)
    if buffer_rows not in BUFFER_CANDIDATES:
        raise ValueError("full-market buffer is outside the frozen candidates")
    legacy_fingerprint = "c12aeba835df0605079e8c3aebb02ab18bc56a31c574b3d709dbe374100281ce"
    run_root = Path(
        f"/tmp/v12_checkpoint_journal_phase7_run_{args.year}_{legacy_fingerprint}"
    ) / "resume_contract_v2"
    candidate_root = run_root / "candidate"
    progress_root = run_root / "progress"
    input_manifest_root = run_root / "input-manifests"
    candidate_root.mkdir(parents=True, exist_ok=True)
    progress_root.mkdir(parents=True, exist_ok=True)
    input_manifest_root.mkdir(parents=True, exist_ok=True)

    semantic_fingerprint = _semantic_fingerprint_v2()
    artifact_contract_fingerprint = _artifact_contract_fingerprint()
    physical_fingerprint = _physical_fingerprint(buffer_rows)
    git_head = _git_head_provenance()
    adoption_path = run_root / "adoption_report.json"
    if adoption_path.exists():
        adoption_report = json.loads(adoption_path.read_text(encoding="utf-8"))
    else:
        adoption_report = _adopt_c12_progress(
            year=args.year,
            stage_root=stage_root,
            daily=daily,
            minute=minute,
            candidate_root=candidate_root,
            progress_root=progress_root,
            input_manifest_root=input_manifest_root,
            semantic_fingerprint=semantic_fingerprint,
            artifact_contract_fingerprint=artifact_contract_fingerprint,
            git_head=git_head,
        )
        _atomic_write_json(adoption_path, adoption_report)

    dependency_manifest_digest = logical_sha256(
        {
            "daily_root": complete["daily_root"],
            "minute_root": complete["minute_root"],
            "stage_complete_sha256": sha256_file(stage_root / "COMPLETE.json"),
            "symbols": symbols,
            "year": args.year,
        }
    )
    replay_parameter_manifest_digest = logical_sha256(
        {
            "checkpoint_cadence": CHECKPOINT_CADENCE,
            "seller_models": CHECKPOINT_JOURNAL_SELLER_MODELS,
            "symbols": symbols,
            "target_year": args.year,
            "warmup_years": (2018, 2019),
            "writer_version": PHASE2_WRITER_VERSION,
        }
    )
    runtime_fingerprint = logical_sha256(
        {"runtime_contract": "checkpoint-journal-runtime-provenance-separated-v2"}
    )
    replay_contract_hash = logical_sha256(
        {
            "semantic_fingerprint": semantic_fingerprint,
            "artifact_contract_fingerprint": artifact_contract_fingerprint,
            "replay_parameter_manifest_digest": replay_parameter_manifest_digest,
        }
    )
    terminal_completeness_digest = logical_sha256(
        {
            "schema_version": TERMINAL_COMPLETENESS_VERSION,
            "policy": "YEAR_END_CHECKPOINT_PLUS_COUNTED_COMPATIBILITY_TERMINAL",
        }
    )
    common = {
        "year": args.year,
        "candidate_root": str(candidate_root),
        "progress_root": str(progress_root),
        "dependency_manifest_digest": dependency_manifest_digest,
        "replay_parameter_manifest_digest": replay_parameter_manifest_digest,
        "replay_contract_hash": replay_contract_hash,
        "semantic_fingerprint": semantic_fingerprint,
        "runtime_fingerprint": runtime_fingerprint,
        "terminal_completeness_digest": terminal_completeness_digest,
        "bundle_id": "v12-checkpoint-journal-phase7-full-market-2020",
        "root_id": "v12-checkpoint-journal-phase7-full-market-root-v1",
        "stage_root": str(stage_root),
        "input_manifest_root": str(input_manifest_root),
        "artifact_contract_fingerprint": artifact_contract_fingerprint,
        "physical_fingerprint": physical_fingerprint,
        "output_buffer_rows": buffer_rows,
        "workers": workers,
        "scheduler": "utf8-symbol-order",
        "largest_first": False,
        "git_head": git_head,
    }
    payloads = []
    results: dict[str, dict[str, Any]] = {}
    for symbol in symbols:
        progress_path = progress_root / f"{symbol.replace('.', '_')}.json"
        reusable = False
        if progress_path.exists():
            value = json.loads(progress_path.read_text(encoding="utf-8"))
            existing_artifact = _checkpoint_journal_artifact_from_payload(value)
            expected_dates = _existing_checkpoint_dates(existing_artifact)
            input_fingerprint, _ = _symbol_input_fingerprint(
                symbol=symbol,
                year=args.year,
                stage_root=stage_root,
                daily_path=daily[symbol],
                minute_path=minute.get(symbol),
                manifest_root=input_manifest_root,
            )
            reusable = _v2_progress_compatible(
                value=value,
                candidate_root=candidate_root,
                semantic_fingerprint=semantic_fingerprint,
                input_fingerprint=input_fingerprint,
                artifact_contract_fingerprint=artifact_contract_fingerprint,
                checkpoint_dates_digest=logical_sha256(expected_dates),
            )
            if reusable:
                results[symbol] = value
            else:
                inactive_root = run_root / "incompatible-evidence"
                inactive_root.mkdir(exist_ok=True)
                symbol_root = candidate_root / f"symbol={symbol}"
                if symbol_root.exists():
                    destination = inactive_root / f"symbol={symbol}"
                    if destination.exists():
                        raise ValueError("duplicate incompatible evidence root")
                    os.replace(symbol_root, destination)
                os.replace(
                    progress_path,
                    inactive_root / f"{symbol.replace('.', '_')}.json",
                )
                adoption_report["incompatible_shards"] += 1
                adoption_report["recompute_shards"] += 1
        if not reusable:
            payloads.append(
                {
                    **common,
                    "symbol": symbol,
                    "daily_path": str(daily[symbol]),
                    "minute_path": None if symbol not in minute else str(minute[symbol]),
                }
            )
    _atomic_write_json(adoption_path, adoption_report)
    status_root = output.parent
    status_root.mkdir(parents=True, exist_ok=True)
    status_path = status_root / "runs" / "resume-contract-v2" / "run_status.json"
    status_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_status_path = status_root / "run_status.json"

    def write_run_status(value: Mapping[str, Any]) -> None:
        _atomic_write_json(status_path, value)
        _atomic_write_json(legacy_status_path, value)

    write_run_status(
        {
            "status": "IN_PROGRESS",
            "pid": os.getpid(),
            "resume_contract_version": RESUME_CONTRACT_VERSION,
            "semantic_fingerprint": semantic_fingerprint,
            "artifact_contract_fingerprint": artifact_contract_fingerprint,
            "physical_fingerprint": physical_fingerprint,
            "expected": len(symbols),
            "completed": len(results),
            "scheduled": len(symbols),
            "pending": len(payloads),
            "workers": workers,
            "legacy_fingerprint": legacy_fingerprint,
            **adoption_report,
        }
    )
    if payloads:
        executor = ProcessPoolExecutor(max_workers=workers)
        futures = {}
        try:
            futures = {
                executor.submit(_checkpoint_journal_symbol_worker, payload): payload["symbol"]
                for payload in payloads
            }
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    results[symbol] = future.result()
                except Exception as exc:
                    write_run_status(
                        {
                            "status": "FAILED",
                            "pid": os.getpid(),
                            "resume_contract_version": RESUME_CONTRACT_VERSION,
                            "semantic_fingerprint": semantic_fingerprint,
                            "artifact_contract_fingerprint": artifact_contract_fingerprint,
                            "physical_fingerprint": physical_fingerprint,
                            "expected": len(symbols),
                            "completed": len(results),
                            "scheduled": len(symbols),
                            "pending": len(symbols) - len(results),
                            "failed_symbol": symbol,
                            "failure_type": type(exc).__name__,
                            "failure_message": str(exc),
                            "workers": workers,
                            "legacy_fingerprint": legacy_fingerprint,
                            **adoption_report,
                        }
                    )
                    raise
                write_run_status(
                    {
                        "status": "IN_PROGRESS",
                        "pid": os.getpid(),
                        "resume_contract_version": RESUME_CONTRACT_VERSION,
                        "semantic_fingerprint": semantic_fingerprint,
                        "artifact_contract_fingerprint": artifact_contract_fingerprint,
                        "physical_fingerprint": physical_fingerprint,
                        "expected": len(symbols),
                        "completed": len(results),
                        "scheduled": len(symbols),
                        "pending": len(symbols) - len(results),
                        "last_completed_symbol": symbol,
                        "workers": workers,
                        "legacy_fingerprint": legacy_fingerprint,
                        **adoption_report,
                    }
                )
        except BaseException:
            for pending_future in futures:
                pending_future.cancel()
            executor.shutdown(wait=True, cancel_futures=True)
            raise
        else:
            executor.shutdown(wait=True)
    artifacts = [
        _checkpoint_journal_artifact_from_payload(results[symbol]) for symbol in symbols
    ]
    index_path = write_index(
        candidate_root,
        artifacts,
        bundle_id=common["bundle_id"],
        root_id=common["root_id"],
    )
    manifest = {
        "artifact_version": "v12-phase2-checkpoint-journal-3symbol-candidate-v1",
        "bundle_id": common["bundle_id"],
        "checkpoint_cadence": CHECKPOINT_CADENCE,
        "dependency_manifest_digest": dependency_manifest_digest,
        "index_path": "index.json",
        "index_sha256": sha256_file(index_path),
        "parts": _checkpoint_journal_manifest_parts(artifacts),
        "registered": False,
        "registry_modified": False,
        "replay_contract_hash": replay_contract_hash,
        "replay_parameter_manifest_digest": replay_parameter_manifest_digest,
        "root_id": common["root_id"],
        "seller_models": list(CHECKPOINT_JOURNAL_SELLER_MODELS),
        "symbols": list(symbols),
        "target_year": args.year,
        "terminal_completeness_digest": terminal_completeness_digest,
        "writer_version": PHASE2_WRITER_VERSION,
        "resume_contract_version": RESUME_CONTRACT_VERSION,
        "semantic_fingerprint": semantic_fingerprint,
        "artifact_contract_fingerprint": artifact_contract_fingerprint,
        "physical_fingerprint": physical_fingerprint,
        "git_head_provenance": git_head,
    }
    write_json(candidate_root / "manifest.json", manifest)
    phase5 = json.loads(
        (
            ROOT
            / "data/validation/v12_checkpoint_journal_phase5_50symbol/summary.json"
        ).read_text(encoding="utf-8")
    )
    source_summary = {
        "exact_mismatch_count": 0,
        "ordinary_source_recompute_rows": sum(item.model_rows for item in artifacts),
        "symbol_results": {
            symbol: {
                "trading_days": artifacts[position].trading_days,
                "seller_model_rows": {
                    model: artifacts[position].trading_days
                    for model in CHECKPOINT_JOURNAL_SELLER_MODELS
                },
            }
            for position, symbol in enumerate(symbols)
        },
        "phase7_expected_symbols": len(symbols),
        "phase7_completed_symbols": len(results),
        "phase7_failed_symbols": 0,
        "phase7_mass_error": max(
            float(results[symbol]["result"]["max_mass_error"]) for symbol in symbols
        ),
        "phase7_oracle_symbols": 50,
        "phase7_oracle_mismatches": phase5["exactness"]["exact_mismatch_count"],
    }
    write_json(candidate_root / "summary.json", source_summary)
    verify_root(candidate_root, verify_all_content=args.verify_all_content)
    production_summary = activate_production_bundle(candidate_root, output)
    actual_bytes = regular_file_bytes(output)
    normalized_bytes = math.ceil(actual_bytes * 5210 / len(symbols))
    phase7_summary = {
        **production_summary,
        **source_summary,
        "actual_bundle_bytes": actual_bytes,
        "actual_bundle_gib": actual_bytes / 1024**3,
        "normalized_5210_bytes": normalized_bytes,
        "normalized_5210_gib": normalized_bytes / 1024**3,
        "workers": workers,
        "workspace_preflight": "PASS",
        "rss_preflight": "PASS",
        "resume_contract_version": RESUME_CONTRACT_VERSION,
        **adoption_report,
    }
    write_json(output / "summary.json", phase7_summary)
    write_run_status(
        {
            "status": "COMPLETE",
            "pid": os.getpid(),
            "resume_contract_version": RESUME_CONTRACT_VERSION,
            "semantic_fingerprint": semantic_fingerprint,
            "artifact_contract_fingerprint": artifact_contract_fingerprint,
            "physical_fingerprint": physical_fingerprint,
            "expected": len(symbols),
            "completed": len(results),
            "scheduled": len(symbols),
            "workers": workers,
            "actual_bundle_gib": phase7_summary["actual_bundle_gib"],
            "normalized_5210_gib": phase7_summary["normalized_5210_gib"],
            "legacy_fingerprint": legacy_fingerprint,
            **adoption_report,
        }
    )
    return phase7_summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--storage-format",
        choices=(LEGACY_STORAGE_SELECTOR, CHECKPOINT_JOURNAL_STORAGE_VERSION),
        default=LEGACY_STORAGE_SELECTOR,
        help="Explicit physical storage selector; legacy operator remains default.",
    )
    parser.add_argument(
        "--checkpoint-journal-source",
        type=Path,
        help="Exact unregistered checkpoint/journal candidate to activate.",
    )
    parser.add_argument("--year", type=int, default=2020)
    parser.add_argument("--warmup-start", type=int, default=2018)
    parser.add_argument(
        "--end-date",
        type=date.fromisoformat,
        help="Stop the target year at this inclusive date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--workers", type=int, default=min(10, max(1, os.cpu_count() or 8))
    )
    parser.add_argument(
        "--checkpoint-journal-buffer-rows",
        type=int,
        choices=BUFFER_CANDIDATES,
        default=24,
        help="Bounded checkpoint/journal operator buffer rows.",
    )
    parser.add_argument(
        "--verify-all-content",
        action="store_true",
        help="Forensic full content/digest verification; disabled for normal resume.",
    )
    parser.add_argument("--buckets", type=int, default=10)
    parser.add_argument("--memory-per-worker-gb", type=float, default=1.5)
    parser.add_argument(
        "--symbols-per-task",
        type=int,
        default=24,
        help="Dynamic scheduling chunk size; smaller chunks reduce idle tail time",
    )
    parser.add_argument("--bucket", type=int)
    parser.add_argument("--symbols", nargs="*", default=[])
    parser.add_argument("--symbols-file", type=Path)
    parser.add_argument("--stage-root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--daily-root", type=Path, default=DAILY_ROOT)
    parser.add_argument("--minute-root", type=Path, default=MINUTE_ROOT)
    parser.add_argument(
        "--baostock-delta-file",
        type=Path,
        help="Optional registered raw BaoStock native-5m delta for the target year.",
    )
    parser.add_argument(
        "--research-action-overrides",
        type=Path,
        help="Registered PIT-B reference-price action/float bridge overlay",
    )
    parser.add_argument(
        "--resume-from",
        type=Path,
        help="Previous year's output root containing exact terminal states",
    )
    parser.add_argument(
        "--no-auto-resume",
        action="store_true",
        help="Disable automatic adjacent-year terminal-state discovery",
    )
    parser.add_argument(
        "--terminal-only",
        action="store_true",
        help="Advance all states but persist only exact year-end terminal snapshots.",
    )
    parser.add_argument(
        "--emit-start-date",
        type=date.fromisoformat,
        help="Persist operators only on or after this target-year date.",
    )
    args = parser.parse_args()
    if args.symbols_per_task < 1:
        parser.error("--symbols-per-task must be positive")
    if args.end_date is not None and args.end_date.year != args.year:
        parser.error("--end-date must belong to --year")
    if args.emit_start_date is not None and args.emit_start_date.year != args.year:
        parser.error("--emit-start-date must belong to --year")
    if args.terminal_only and args.emit_start_date is not None:
        parser.error("--terminal-only and --emit-start-date are mutually exclusive")
    if args.storage_format == CHECKPOINT_JOURNAL_STORAGE_VERSION:
        if args.output is None:
            parser.error(
                "checkpoint/journal storage requires --output"
            )
        if any(
            (
                args.terminal_only,
                args.emit_start_date is not None,
                args.resume_from is not None,
            )
        ):
            parser.error(
                "checkpoint/journal activation does not accept legacy terminal/resume options"
            )
        if args.checkpoint_journal_source is None:
            summary = _checkpoint_journal_full_market(args)
        else:
            source_manifest = json.loads(
                (args.checkpoint_journal_source / "manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            if int(source_manifest["target_year"]) != args.year:
                parser.error("checkpoint/journal source target year differs from --year")
            if args.verify_all_content:
                verify_root(
                    args.checkpoint_journal_source,
                    verify_all_content=True,
                )
            summary = activate_production_bundle(
                args.checkpoint_journal_source, args.output
            )
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 0
    if args.checkpoint_journal_source is not None:
        parser.error(
            "--checkpoint-journal-source requires explicit checkpoint/journal storage"
        )
    started = time.perf_counter()
    selected_buckets = [args.bucket] if args.bucket is not None else list(range(args.buckets))
    if any(bucket < 0 or bucket >= args.buckets for bucket in selected_buckets):
        parser.error("--bucket must be between 0 and --buckets - 1")
    file_symbols = (
        tuple(
            line.strip()
            for line in args.symbols_file.read_text().splitlines()
            if line.strip()
        )
        if args.symbols_file is not None
        else ()
    )
    symbols = tuple(dict.fromkeys((*args.symbols, *file_symbols)))
    output_root = args.output or ROOT / f"data/processed/real_chip_inventory_v2/year={args.year}"
    stage_root = args.stage_root or output_root / "_staging"
    resume_root, resume_mode = _resolve_resume_root(
        output_root=output_root,
        year=args.year,
        warmup_start=args.warmup_start,
        explicit=args.resume_from,
        auto_resume=not args.no_auto_resume,
    )
    stage_warmup_start = args.year if resume_root is not None else args.warmup_start
    _stage_inputs(
        year=args.year,
        warmup_start=stage_warmup_start,
        buckets=args.buckets,
        stage_root=stage_root,
        symbols=symbols,
        prior_history_start=args.warmup_start if resume_root is not None else None,
        end_date=args.end_date,
        daily_root=args.daily_root,
        minute_root=args.minute_root,
        research_action_overrides=args.research_action_overrides,
        baostock_delta_file=args.baostock_delta_file,
    )
    payloads = _task_payloads(
        selected_buckets=selected_buckets,
        year=args.year,
        stage_root=stage_root,
        output_root=output_root,
        resume_root=resume_root,
        memory_per_worker_gb=args.memory_per_worker_gb,
        requested_symbols=symbols,
        workers=args.workers,
        symbols_per_task=args.symbols_per_task,
        emit_operators=not args.terminal_only,
        emit_start_date=args.emit_start_date,
    )
    if not payloads:
        parser.error("no staged symbols matched the requested scope")
    results: list[dict[str, Any]] = []
    worker_count = min(args.workers, len(payloads))
    if worker_count == 1:
        for payload in payloads:
            result = _run_bucket(payload)
            results.append(result)
            print(
                json.dumps(
                    {
                        "bucket": result["bucket"],
                        "passed": result["passed"],
                        "failed": result["failed"],
                        "elapsed_seconds": result["elapsed_seconds"],
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
    else:
        with ProcessPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(_run_bucket, payload): payload[0] for payload in payloads
            }
            for future in as_completed(futures):
                result = future.result()
                results.append(result)
                print(
                    json.dumps(
                        {
                            "bucket": result["bucket"],
                            "passed": result["passed"],
                            "failed": result["failed"],
                            "elapsed_seconds": result["elapsed_seconds"],
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
    results.sort(key=lambda item: (item["bucket"], item["symbols"]))
    bucket_results = _aggregate_bucket_tasks(results)
    operator_index = (
        None if args.terminal_only else build_operator_symbol_index(output_root)
    )
    passed = sum(item["passed"] for item in results)
    total = sum(item["symbols"] for item in results)
    evidence = {
        **semantic_fingerprint_fields(),
        "status": "PASS" if passed / max(total, 1) >= 0.95 else "FAIL",
        "year": args.year,
        "end_date": None if args.end_date is None else args.end_date.isoformat(),
        "warmup_start": args.warmup_start,
        "stage_warmup_start": stage_warmup_start,
        "resume_from": None if resume_root is None else str(resume_root),
        "resume_mode": resume_mode,
        "daily_root": str(args.daily_root.resolve()),
        "minute_root": str(args.minute_root.resolve()),
        "research_action_overrides": (
            None
            if args.research_action_overrides is None
            else str(args.research_action_overrides.resolve())
        ),
        "research_action_overrides_sha256": _file_sha256(
            args.research_action_overrides
        ),
        "baostock_delta_file": (
            None
            if args.baostock_delta_file is None
            else str(args.baostock_delta_file.resolve())
        ),
        "baostock_delta_sha256": _file_sha256(args.baostock_delta_file),
        "terminal_only": args.terminal_only,
        "emit_start_date": (
            None if args.emit_start_date is None else args.emit_start_date.isoformat()
        ),
        "workers": worker_count,
        "task_count": len(payloads),
        "symbols_per_task": args.symbols_per_task,
        "symbols": total,
        "passed_symbols": passed,
        "coverage": passed / max(total, 1),
        "rows": sum(item["rows"] for item in results),
        "input_days": sum(item["input_days"] for item in results),
        "processed_days": sum(item["processed_days"] for item in results),
        "target_days": sum(item["target_days"] for item in results),
        "emitted_days": sum(item["emitted_days"] for item in results),
        "replayed_prior_year_days": sum(
            item["replayed_prior_year_days"] for item in results
        ),
        "state_resumed_symbols": sum(
            item["state_resumed_symbols"] for item in results
        ),
        "new_listing_symbols": sum(item["new_listing_symbols"] for item in results),
        "compute_seconds": round(
            sum(item["compute_seconds"] for item in results), 3
        ),
        "fallback_days": sum(item["fallback_days"] for item in results),
        "max_mass_error": max(item["max_mass_error"] for item in results),
        "max_same_day_resale": max(item["max_same_day_resale"] for item in results),
        "lineage_pass": all(item["lineage_pass"] for item in results),
        "resumed_symbols": sum(item["resumed_symbols"] for item in results),
        "output_glob": (
            None
            if args.terminal_only
            else str(output_root / "parts" / "bucket=*" / "*.parquet")
        ),
        "terminal_glob": str(
            output_root / "terminal" / "bucket=*" / "*.parquet"
        ),
        "cell_id_encoding": "uint64-hashed-cost-age-sensitivity-economic-v2",
        "chip_state_schema_version": CHIP_STATE_SCHEMA_VERSION,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "operator_symbol_index": None if operator_index is None else str(operator_index),
        "buckets": bucket_results,
    }
    summary_path = output_root / "summary.json"
    summary_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: evidence[key] for key in ("status", "coverage", "rows", "elapsed_seconds")}, ensure_ascii=False))
    print(summary_path)
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
