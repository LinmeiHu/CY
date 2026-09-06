import importlib.util
import struct
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

from cyq_game.chip.migration_v2 import StableLogPriceGrid, initial_unknown_snapshot
from cyq_game.chip.peaks import EnsembleTemporalPeakTracker
from cyq_game.chip.state_v2 import (
    ChipSnapshotV2,
    InventoryCell,
    SellerModel,
    SnapshotPhase,
    SparseChipInventory,
    TurnoverSensitivity,
)


SCRIPT = Path(__file__).parents[1] / "scripts/prototype_chip_checkpoint_recompute.py"
SPEC = importlib.util.spec_from_file_location("checkpoint_prototype_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _bits(value: float) -> int:
    return struct.unpack("<Q", struct.pack("<d", value))[0]


def _snapshots() -> dict[SellerModel, ChipSnapshotV2]:
    timestamp = datetime(2020, 1, 31, 15, tzinfo=ZoneInfo("Asia/Shanghai"))
    grid = StableLogPriceGrid(1.0, 0.0025, MODULE.BUILD.GRID_VERSION)
    shared = InventoryCell.create(
        cost_bucket_id=grid.bucket_for_price(10.0),
        holding_days=12,
        sensitivity=TurnoverSensitivity.NEUTRAL,
        acquisition_cost=10.0,
        economic_break_even=9.75,
        shares=600.0,
        initialization_prior_units=0.25,
    )
    result = {}
    for index, model in enumerate(MODULE.SELLER_MODEL_ORDER):
        unique = InventoryCell.create(
            cost_bucket_id=grid.bucket_for_price(11.0 + index),
            holding_days=3 + index,
            sensitivity=TurnoverSensitivity.ACTIVE,
            acquisition_cost=11.0 + index,
            economic_break_even=10.5 + index,
            shares=400.0,
        )
        cells = (
            InventoryCell.create(
                cost_bucket_id=shared.cost_bucket_id,
                holding_days=shared.holding_days,
                sensitivity=shared.sensitivity,
                acquisition_cost=shared.acquisition_cost,
                economic_break_even=shared.economic_break_even,
                shares=shared.shares,
                initialization_prior_units=shared.initialization_prior_units,
            ),
            unique,
        )
        inventory = SparseChipInventory.canonical(cells)
        seed = initial_unknown_snapshot(
            symbol="000001.SZ",
            decision_at=timestamp,
            available_at=timestamp,
            free_float_shares=1_000.0,
            latent_supply_shares=0.0,
            seller_model=model,
            model_version=MODULE.BUILD.MODEL_VERSION,
            grid_version=MODULE.BUILD.GRID_VERSION,
            input_snapshot_ids=("registered:daily",),
        )
        result[model] = ChipSnapshotV2(
            symbol=seed.symbol,
            trading_date=date(2020, 1, 31),
            decision_at=timestamp,
            effective_at=timestamp,
            available_at=timestamp,
            phase=SnapshotPhase.POST,
            snapshot_id=f"snapshot-{model.value}",
            model_version=seed.model_version,
            grid_version=seed.grid_version,
            seller_model=model,
            inventory=inventory,
            free_float_shares=1_000.0,
            latent_supply_shares=0.0,
            input_snapshot_ids=("registered:daily",),
            pit_grade="A",
            hard_valid=True,
        )
    return result


def test_union_checkpoint_roundtrip_preserves_all_ieee_bits(tmp_path: Path) -> None:
    snapshots = _snapshots()
    tracker = EnsembleTemporalPeakTracker(
        symbol="000001.SZ", models=MODULE.TRACKER_MODELS
    )
    checkpoint = MODULE.Checkpoint("month-01", snapshots, tracker)
    path = tmp_path / "checkpoint.npz"

    stats = MODULE.write_checkpoint(path, checkpoint)
    restored, restored_tracker = MODULE.load_checkpoint(path)

    assert stats["independent_identities"] == 6
    assert stats["union_identities"] == 4
    for model in MODULE.SELLER_MODEL_ORDER:
        assert MODULE._snapshot_digest(restored[model]) == MODULE._snapshot_digest(
            snapshots[model]
        )
        assert MODULE._continuation_digest(restored[model]) == MODULE._continuation_digest(
            snapshots[model]
        )
        expected = snapshots[model].inventory.cells
        actual = restored[model].inventory.cells
        assert [_bits(cell.shares) for cell in actual] == [
            _bits(cell.shares) for cell in expected
        ]
        assert [_bits(cell.economic_break_even) for cell in actual] == [
            _bits(cell.economic_break_even) for cell in expected
        ]
    assert MODULE._tracker_digest(restored_tracker) == MODULE._tracker_digest(tracker)


def test_checkpoint_and_journal_npz_have_no_object_arrays(tmp_path: Path) -> None:
    snapshots = _snapshots()
    checkpoint = MODULE.Checkpoint(
        "month-01",
        snapshots,
        EnsembleTemporalPeakTracker(symbol="000001.SZ", models=MODULE.TRACKER_MODELS),
    )
    checkpoint_path = tmp_path / "checkpoint.npz"
    MODULE.write_checkpoint(checkpoint_path, checkpoint)
    evidence = MODULE.DayEvidence(
        trading_date=date(2020, 1, 31),
        input_digest=b"i" * 32,
        input_refs=("daily:test", "minute-day-sha256:test"),
        action_refs=(),
        cash_bits=_bits(0.0),
        multiplier_bits=_bits(1.0),
        circulating_bits=_bits(1_000.0),
        model_hashes=(b"m" * 32,) * 3,
        transition_hashes=(b"t" * 32,) * 3,
        runtime_hashes=(b"r" * 32,) * 3,
        operator_digests=(b"o" * 32,) * 3,
        post_digests=(b"p" * 32,) * 3,
        identity_digests=(b"d" * 32,) * 3,
        share_digests=(b"s" * 32,) * 3,
        feature_digest=b"f" * 32,
        snapshot_ids=("s0", "s1", "s2"),
        transition_ids=("t0", "t1", "t2"),
    )
    journal_path = tmp_path / "journal.npz"
    MODULE.write_journal(journal_path, [evidence])

    for path in (checkpoint_path, journal_path):
        with np.load(path, allow_pickle=False) as archive:
            assert all(archive[name].dtype.kind != "O" for name in archive.files)
    with np.load(journal_path, allow_pickle=False) as journal:
        forbidden = ("destination", "retention", "inventory", "shares")
        assert not any(any(token in name for token in forbidden) for name in journal.files)


def test_digest_distinguishes_adjacent_float_bits() -> None:
    left = 1.0
    right = np.nextafter(left, 2.0)
    assert MODULE._digest(left) != MODULE._digest(right)


def test_result_cache_is_atomic_and_fingerprint_gated(tmp_path: Path) -> None:
    symbol = "000001.SZ"
    symbol_root = tmp_path / f"symbol={symbol}"
    result = {"symbol": symbol, "benchmark_mode": "fast", "value": 7}

    MODULE._write_cached_result(symbol_root, "fingerprint-a", result)

    assert MODULE._load_cached_result(tmp_path, symbol, "fingerprint-a") == result
    assert MODULE._load_cached_result(tmp_path, symbol, "fingerprint-b") is None
    assert not list(symbol_root.glob("*.tmp"))
