from __future__ import annotations

import json
import math
import struct
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Sequence

import pyarrow.parquet as pq

from cyq_game.chip.checkpoint_journal_contract import bits_f64be
from cyq_game.chip.checkpoint_journal_reader import (
    CheckpointJournalReader,
    DependencyCatalog,
    DependencyRecord,
    ReplayStep,
    derive_economic_bucket,
)
from cyq_game.chip.checkpoint_journal_writer import PHASE2_SYMBOLS
from cyq_game.chip.checkpoint_codec import decode_checkpoint
from cyq_game.chip.journal_codec import JournalDay, decode_journal
from cyq_game.chip.migration_v2 import (
    StableLogPriceGrid,
    bucket_for_economic_break_even,
    economic_break_even_for_bucket,
)
from cyq_game.chip.state_v2 import SellerModel
from cyq_game.strategy.chip_lineage import (
    PersistedChipLineageResolver,
    _lineage_operator,
)

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "data/validation/v12_checkpoint_journal_phase2_3symbol"
LEGACY = ROOT / "data/validation/v12_rc1_2020_output"
GRID = StableLogPriceGrid(1.0, 0.0025, "log-grid-25bp-v1")


def _bits(value: float) -> int:
    return struct.unpack(">Q", struct.pack(">d", value))[0]


def _exact_equal(left: Any, right: Any) -> bool:
    if isinstance(left, float) and isinstance(right, float):
        return _bits(left) == _bits(right)
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        return set(left) == set(right) and all(
            _exact_equal(left[key], right[key]) for key in left
        )
    if isinstance(left, Sequence) and isinstance(right, Sequence) and not isinstance(
        left, (str, bytes, bytearray)
    ):
        return len(left) == len(right) and all(
            _exact_equal(a, b) for a, b in zip(left, right, strict=True)
        )
    return left == right


def _assert_parquet_logical_exact(actual: Path, expected: Path) -> int:
    actual_table = pq.ParquetFile(actual).read()
    expected_table = pq.ParquetFile(expected).read()
    assert actual_table.schema == expected_table.schema
    actual_rows = actual_table.to_pylist()
    expected_rows = expected_table.to_pylist()
    assert len(actual_rows) == len(expected_rows)
    mismatches = sum(
        not _exact_equal(left, right)
        for left, right in zip(actual_rows, expected_rows, strict=True)
    )
    assert mismatches == 0
    return mismatches


@dataclass(frozen=True)
class _LogicalModelState:
    cell_ids: tuple[int, ...]
    share_bits: tuple[int, ...]
    # The legacy resolver exposes only a coarse compatibility bucket.  Keep it
    # available to drive the frozen legacy dependency primitive, but exclude it
    # from numeric exact-oracle equality.
    economic_buckets: tuple[int | None, ...] = field(compare=False, repr=False)
    total_mass_bits: int
    snapshot_id: str
    free_float_bits: int
    hard_valid: bool
    quality_reason_codes: tuple[str, ...]
    input_snapshot_digest: bytes


@dataclass(frozen=True)
class _LogicalDayState:
    symbol: str
    trading_date: date
    models: Mapping[SellerModel, _LogicalModelState]


def _logical_model(
    inventory: Mapping[int, float],
    economic: Mapping[int, int | None],
    row: Mapping[str, Any],
) -> _LogicalModelState:
    # The storage contract's canonical logical order is ascending stable cell
    # identity.  Legacy checkpoint arrays predate that contract and may retain
    # construction order, so normalize the old resolver mapping to the same
    # explicit order before the bit-for-bit comparison.
    cell_ids = tuple(sorted(inventory))
    return _LogicalModelState(
        cell_ids=cell_ids,
        share_bits=tuple(_bits(inventory[cell_id]) for cell_id in cell_ids),
        economic_buckets=tuple(economic[cell_id] for cell_id in cell_ids),
        total_mass_bits=_bits(math.fsum(inventory.values())),
        snapshot_id=str(row["snapshot_id"]),
        free_float_bits=_bits(float(row["free_float_shares"])),
        hard_valid=bool(row["hard_valid"]),
        quality_reason_codes=tuple(str(value) for value in row["quality_reason_codes"]),
        input_snapshot_digest=bytes(row["input_snapshot_digest"]),
    )


def _candidate_advance(
    inventory: Mapping[int, float],
    economic_buckets: Mapping[int, int | None],
    row: Mapping[str, Any],
) -> tuple[dict[int, float], dict[int, int | None]]:
    """Independent Phase-3 harness for the frozen dependency primitive.

    The expected stream below is produced by PersistedChipLineageResolver.
    This implementation deliberately performs the operator accumulation itself
    so the new reader result is not reused as its own expected value.
    """

    cash_dividend = float(row.get("cash_dividend_per_share") or 0.0)
    share_multiplier = float(row.get("share_multiplier") or 1.0)
    assert share_multiplier > 0.0
    adjusts_economic = cash_dividend != 0.0 or share_multiplier != 1.0

    def adjusted_bucket(local_id: int) -> int | None:
        bucket = economic_buckets.get(local_id)
        if bucket is None:
            return None
        if not adjusts_economic:
            return bucket
        price = (
            economic_break_even_for_bucket(GRID, bucket) - cash_dividend
        ) / share_multiplier
        return bucket_for_economic_break_even(GRID, price)

    next_inventory: dict[int, float] = {}
    inventory_collisions: dict[int, list[float]] = {}
    economic_parts: dict[
        int, tuple[float, int | None] | list[tuple[float, int | None]]
    ] = {}
    for source, destination, retained in _lineage_operator(inventory, row):
        assert source in inventory
        shares = inventory[source] * retained
        if shares <= 0.0:
            continue
        previous = next_inventory.get(destination)
        if previous is None:
            next_inventory[destination] = shares
        else:
            collision = inventory_collisions.get(destination)
            if collision is None:
                inventory_collisions[destination] = [previous, shares]
            else:
                collision.append(shares)
        part = (shares, adjusted_bucket(source))
        previous_part = economic_parts.get(destination)
        if previous_part is None:
            economic_parts[destination] = part
        elif isinstance(previous_part, tuple):
            economic_parts[destination] = [previous_part, part]
        else:
            previous_part.append(part)
    for local_id, parts in inventory_collisions.items():
        next_inventory[local_id] = math.fsum(parts)
    adjustment_ids = tuple(
        int(value) for value in (row.get("inventory_adjustment_local_ids") or ())
    )
    adjustment_shares = tuple(
        float(value) for value in (row.get("inventory_adjustment_shares") or ())
    )
    raw_adjustment_economic = row.get("inventory_adjustment_economic_bucket_ids")
    assert raw_adjustment_economic is not None
    adjustment_economic = tuple(
        None if value is None else int(value) for value in raw_adjustment_economic
    )
    assert len(adjustment_ids) == len(adjustment_shares) == len(adjustment_economic)
    for local_id, shares in zip(adjustment_ids, adjustment_shares, strict=True):
        next_inventory[local_id] = next_inventory.get(local_id, 0.0) + shares
    next_inventory = {
        local_id: shares for local_id, shares in next_inventory.items() if shares > 0.0
    }

    next_economic: dict[int, int | None] = {}
    for local_id in next_inventory:
        raw_parts = economic_parts.get(local_id)
        if isinstance(raw_parts, tuple):
            next_economic[local_id] = raw_parts[1]
            continue
        parts = raw_parts or []
        known = [(shares, bucket) for shares, bucket in parts if bucket is not None]
        unknown_mass = math.fsum(
            shares for shares, bucket in parts if bucket is None
        )
        if unknown_mass > 0.0 or not known:
            next_economic[local_id] = None
            continue
        total = math.fsum(shares for shares, _ in known)
        price = math.fsum(
            shares * economic_break_even_for_bucket(GRID, int(bucket))
            for shares, bucket in known
        ) / total
        next_economic[local_id] = bucket_for_economic_break_even(GRID, price)
    for local_id, shares, bucket in zip(
        adjustment_ids, adjustment_shares, adjustment_economic, strict=True
    ):
        if shares > 0.0 and local_id in next_inventory:
            next_economic[local_id] = bucket
    return next_inventory, next_economic


def _legacy_rows(symbol: str) -> tuple[
    PersistedChipLineageResolver,
    dict[SellerModel, dict[date, dict[str, Any]]],
]:
    path = (
        LEGACY
        / "parts.__read_forbidden__"
        / "bucket=0"
        / f"{symbol.replace('.', '_')}.parquet"
    )
    resolver = PersistedChipLineageResolver(path)
    rows = resolver._load_symbol(symbol, date(2020, 1, 1), date(2020, 12, 31))
    assert rows is not None
    return resolver, rows


def _legacy_oracle(
    symbol: str,
) -> tuple[
    dict[date, _LogicalDayState],
    dict[SellerModel, dict[date, dict[str, Any]]],
]:
    resolver, rows_by_model = _legacy_rows(symbol)
    by_date: dict[date, dict[SellerModel, _LogicalModelState]] = {}
    for model, rows in rows_by_model.items():
        ordered = sorted(rows)
        opening = rows[ordered[0]]
        inventory = dict(
            zip(
                (int(value) for value in opening["checkpoint_local_ids"]),
                (float(value) for value in opening["checkpoint_shares"]),
                strict=True,
            )
        )
        economic = dict(
            zip(
                (int(value) for value in opening["checkpoint_local_ids"]),
                (
                    None if value is None else int(value)
                    for value in opening["checkpoint_economic_bucket_ids"]
                ),
                strict=True,
            )
        )
        for position, trading_date in enumerate(ordered):
            row = rows[trading_date]
            if position:
                inventory, _, economic = resolver._advance(
                    inventory, None, economic, row
                )
            by_date.setdefault(trading_date, {})[model] = _logical_model(
                inventory, economic, row
            )
    return (
        {
            trading_date: _LogicalDayState(symbol, trading_date, models)
            for trading_date, models in by_date.items()
        },
        rows_by_model,
    )


def _symbol_inputs(
    symbol: str,
) -> tuple[str, tuple[JournalDay, ...], DependencyCatalog]:
    manifest = json.loads((BUNDLE / "manifest.json").read_text(encoding="utf-8"))
    rows = []
    for part in manifest["parts"]:
        relative = part["relative_path"]
        if part["kind"] == "journal" and relative.startswith(f"symbol={symbol}/"):
            rows.extend(decode_journal((BUNDLE / relative).read_bytes()).rows)
    records = {}
    for row in rows:
        for reference in row.dependency_references:
            key = (reference.dependency_class, reference.asset_id, reference.snapshot_id)
            records.setdefault(
                key,
                DependencyRecord(
                    dependency_class=reference.dependency_class,
                    asset_id=reference.asset_id,
                    snapshot_id=reference.snapshot_id,
                    content_digest=reference.content_digest,
                    inventory_digest=reference.inventory_digest,
                ),
            )
    return (
        manifest["replay_parameter_manifest_digest"],
        tuple(rows),
        DependencyCatalog(tuple(records.values())),
    )


class _IndependentDependencyBackend:
    def __init__(
        self,
        symbol: str,
        rows_by_model: dict[SellerModel, dict[date, dict[str, Any]]],
        oracle: Mapping[date, _LogicalDayState],
        seen: set[date],
    ) -> None:
        self.symbol = symbol
        self.rows_by_model = rows_by_model
        self.oracle = oracle
        self.seen = seen

    def restore_checkpoint(self, checkpoint: Any) -> _LogicalDayState:
        assert checkpoint.symbol == self.symbol
        identities = checkpoint.identities
        models: dict[SellerModel, _LogicalModelState] = {}
        for state in checkpoint.model_states:
            model = SellerModel(state.seller_model)
            row = self.rows_by_model[model][checkpoint.checkpoint_date]
            inventory: dict[int, float] = {}
            economic: dict[int, int | None] = {}
            for lot in state.lots:
                identity = identities[lot.identity_position]
                inventory[identity.cell_id] = bits_f64be(lot.shares_bits)
                economic[identity.cell_id] = (
                    derive_economic_bucket(
                        identity.economic_break_even_bits,
                        coordinate_version=identity.economic_coordinate_version,
                    )
                )
            models[model] = _logical_model(inventory, economic, row)
            assert state.snapshot_id == row["snapshot_id"]
            assert state.free_float_shares_bits == _bits(row["free_float_shares"])
            assert state.hard_valid == row["hard_valid"]
            assert state.quality_reason_codes == tuple(row["quality_reason_codes"])
            assert state.seller_continuation.values == {
                "seller_model": model.value,
                "snapshot_id": row["snapshot_id"],
            }
            assert state.lifecycle_continuation.active_anchor_ids == ()
            assert state.lifecycle_continuation.anchors == ()
        value = _LogicalDayState(self.symbol, checkpoint.checkpoint_date, models)
        self._compare(value)
        return value

    def advance_day(self, state: _LogicalDayState, row: JournalDay) -> ReplayStep:
        models: dict[SellerModel, _LogicalModelState] = {}
        for model, previous in state.models.items():
            operator_row = self.rows_by_model[model][row.trading_date]
            inventory = dict(
                zip(
                    previous.cell_ids,
                    (bits_f64be(value) for value in previous.share_bits),
                    strict=True,
                )
            )
            economic = dict(
                zip(previous.cell_ids, previous.economic_buckets, strict=True)
            )
            inventory, economic = _candidate_advance(
                inventory, economic, operator_row
            )
            models[model] = _logical_model(inventory, economic, operator_row)
            input_hex = bytes(operator_row["input_snapshot_digest"]).hex()
            assert f"input-digest:{input_hex}" in row.input_snapshot_ids
        value = _LogicalDayState(self.symbol, row.trading_date, models)
        self._compare(value)
        return ReplayStep(state=value, model_digests=row.model_digests)

    def _compare(self, actual: _LogicalDayState) -> None:
        expected = self.oracle[actual.trading_date]
        assert actual == expected
        self.seen.add(actual.trading_date)


def test_three_symbol_every_day_logical_replay_and_terminal_are_exact() -> None:
    manifest = json.loads((BUNDLE / "manifest.json").read_text(encoding="utf-8"))
    total_days = 0
    total_ca_days = 0
    total_zero_sell_model_days = 0
    legacy_bucket_diagnostic_count = 0
    known_case_seen = False
    for symbol in PHASE2_SYMBOLS:
        digest, rows, catalog = _symbol_inputs(symbol)
        oracle, rows_by_model = _legacy_oracle(symbol)
        reader = CheckpointJournalReader(
            BUNDLE,
            replay_parameter_manifest_digest=digest,
            dependency_catalog=catalog,
        )
        coverage = [row for row in reader.index.rows if row.symbol == symbol]
        checkpoint_parts = [
            part
            for part in manifest["parts"]
            if part["kind"] == "checkpoint"
            and part["relative_path"].startswith(f"symbol={symbol}/")
        ]
        assert len(checkpoint_parts) == 13
        for checkpoint_part in checkpoint_parts:
            checkpoint = decode_checkpoint(
                (BUNDLE / checkpoint_part["relative_path"]).read_bytes()
            )
            identity_by_id = {
                identity.cell_id: identity for identity in checkpoint.identities
            }
            for identity in checkpoint.identities:
                bits = identity.economic_break_even_bits
                if bits is not None:
                    assert _bits(bits_f64be(bits)) == bits
                first = derive_economic_bucket(
                    bits,
                    coordinate_version=identity.economic_coordinate_version,
                )
                second = derive_economic_bucket(
                    bits,
                    coordinate_version=identity.economic_coordinate_version,
                )
                assert first == second
            for state in checkpoint.model_states:
                model = SellerModel(state.seller_model)
                expected = oracle[checkpoint.checkpoint_date].models[model]
                legacy_by_id = dict(
                    zip(
                        expected.cell_ids,
                        expected.economic_buckets,
                        strict=True,
                    )
                )
                for lot in state.lots:
                    identity = identity_by_id[
                        checkpoint.identities[lot.identity_position].cell_id
                    ]
                    derived = derive_economic_bucket(
                        identity.economic_break_even_bits,
                        coordinate_version=identity.economic_coordinate_version,
                    )
                    legacy = legacy_by_id[identity.cell_id]
                    if derived != legacy:
                        legacy_bucket_diagnostic_count += 1
                    if (
                        symbol == "002706.SZ"
                        and checkpoint.checkpoint_date == date(2020, 4, 30)
                        and identity.cell_id == 605583525273912
                    ):
                        assert identity.economic_break_even_bits == 4618404864918200488
                        assert derived == 715
                        assert legacy == 716
                        known_case_seen = True
        seen: set[date] = set()
        for index_row in coverage:
            backend = _IndependentDependencyBackend(
                symbol, rows_by_model, oracle, seen
            )
            result = reader.restore(
                symbol,
                index_row.journal_end_date,
                backend=backend,
            )
            assert result.trading_date == index_row.journal_end_date
        expected_dates = {row.trading_date for row in rows}
        assert len(rows) == 243
        assert len(oracle) == 243
        assert seen == expected_dates
        assert all(len(day.models) == 3 for day in oracle.values())

        feature_part = next(
            part
            for part in manifest["parts"]
            if part["kind"] == "feature"
            and part["relative_path"].startswith(f"symbol={symbol}/")
        )
        _assert_parquet_logical_exact(
            BUNDLE / feature_part["relative_path"],
            LEGACY
            / "daily_feature_fact"
            / "symbol_bucket=0"
            / f"{symbol.replace('.', '_')}.parquet",
        )
        terminal_part = next(
            part
            for part in manifest["parts"]
            if part["kind"] == "terminal"
            and part["relative_path"].startswith(f"symbol={symbol}/")
        )
        _assert_parquet_logical_exact(
            BUNDLE / terminal_part["relative_path"],
            LEGACY
            / "terminal"
            / "bucket=0"
            / f"{symbol.replace('.', '_')}.parquet",
        )
        assert reader.terminal_compatibility_mismatch_count(symbol) == 0
        latest = reader.latest_checkpoint(symbol)
        assert len(latest.model_states) == 3
        assert len(latest.temporal_tracker.scopes) == 4
        assert all(
            state.lifecycle_continuation.active_anchor_ids == ()
            and state.lifecycle_continuation.anchors == ()
            for state in latest.model_states
        )

        representative_rows = rows_by_model[SellerModel.UNIFORM].values()
        total_ca_days += sum(
            (row.get("cash_dividend_per_share") or 0.0) != 0.0
            or (row.get("share_multiplier") or 1.0) != 1.0
            for row in representative_rows
        )
        total_zero_sell_model_days += sum(
            row["executed_sell_shares"] == 0.0
            for model_rows in rows_by_model.values()
            for row in model_rows.values()
        )
        total_days += len(rows)
    assert total_days == 729
    assert total_ca_days == 1
    assert total_zero_sell_model_days > 0
    assert known_case_seen
    assert legacy_bucket_diagnostic_count == 46661
