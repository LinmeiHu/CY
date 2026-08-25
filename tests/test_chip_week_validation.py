from __future__ import annotations

import os
import runpy
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cyq_game.chip import (
    ChipSnapshotV2,
    DailyMigrationEngine,
    InventoryCell,
    InventoryEvent,
    InventoryEventKind,
    MinuteBar,
    SellerModel,
    SnapshotPhase,
    SparseChipInventory,
    StableLogPriceGrid,
    TurnoverSensitivity,
    initial_unknown_snapshot,
)

MODEL_VERSION_PREFIX = "chip-week-v2"
GRID_VERSION = "log-grid-week-v1"
SYMBOLS = tuple(f"{index:06d}.SZ" for index in range(1, 21))
VALIDATION_SCRIPT = Path(__file__).parents[1] / "scripts" / "validate_real_chip_week.py"
VALIDATION_MODULE = runpy.run_path(str(VALIDATION_SCRIPT))
WeekResult = tuple[
    str,
    str,
    tuple[str, ...],
    tuple[float, ...],
    tuple[float, ...],
    float,
    float,
    float,
]


def test_research_week_adapter_does_not_relabel_strict_validity() -> None:
    row = {"hard_valid": False, "research_valid": True}

    assert VALIDATION_MODULE["_selected_validity"](row, "research")
    assert not VALIDATION_MODULE["_selected_validity"](row, "strict")
    assert row["hard_valid"] is False


def test_validity_summary_does_not_count_diagnostic_tag_as_research_failure() -> None:
    rows = [
        {
            "hard_valid": False,
            "research_valid": True,
            "quality_reason_codes": ["UNKNOWN_COST_PRESENT"],
        },
        {
            "hard_valid": False,
            "research_valid": True,
            "quality_reason_codes": ["UNKNOWN_COST_PRESENT"],
        },
    ]

    result = VALIDATION_MODULE["_validity_summary"](rows, "research")

    assert result["diagnostic_tag_rows"] == {"UNKNOWN_COST_PRESENT": 2}
    assert result["strict_invalid_rows"] == 2
    assert result["research_valid_rows"] == 2
    assert result["research_invalid_rows"] == 0
    assert result["research_blocking_tag_rows"] == {}


def _time(day: int, hour: int = 15) -> datetime:
    return datetime(2020, 1, day, hour, tzinfo=UTC)


def _known_initial(symbol: str, seller_model: SellerModel) -> ChipSnapshotV2:
    grid = StableLogPriceGrid(
        reference_price=10.0,
        step_pct=0.01,
        grid_version=GRID_VERSION,
    )
    cell = InventoryCell.create(
        cost_bucket_id=grid.bucket_for_price(10.0),
        holding_days=20,
        sensitivity=TurnoverSensitivity.NEUTRAL,
        acquisition_cost=10.0,
        economic_break_even=10.0,
        shares=100.0,
    )
    return ChipSnapshotV2(
        symbol=symbol,
        trading_date=_time(3).date(),
        decision_at=_time(3),
        effective_at=_time(3),
        available_at=_time(3),
        phase=SnapshotPhase.POST,
        snapshot_id=f"initial-known-{symbol}-{seller_model.value}",
        model_version=f"{MODEL_VERSION_PREFIX}-{seller_model.value}",
        grid_version=GRID_VERSION,
        seller_model=seller_model,
        inventory=SparseChipInventory.canonical((cell,)),
        free_float_shares=100.0,
        latent_supply_shares=0.0,
        input_snapshot_ids=("daily-week", "float-week"),
        pit_grade="A",
        hard_valid=True,
    )


def _initial(symbol: str, seller_model: SellerModel) -> ChipSnapshotV2:
    if symbol in SYMBOLS[:2]:
        return _known_initial(symbol, seller_model)
    return initial_unknown_snapshot(
        symbol=symbol,
        decision_at=_time(3),
        available_at=_time(3),
        free_float_shares=100.0,
        latent_supply_shares=0.0,
        seller_model=seller_model,
        model_version=f"{MODEL_VERSION_PREFIX}-{seller_model.value}",
        grid_version=GRID_VERSION,
        input_snapshot_ids=("daily-week", "float-week"),
    )


def _run_symbol_model(payload: tuple[str, str]) -> WeekResult:
    symbol, raw_model = payload
    seller_model = SellerModel(raw_model)
    grid = StableLogPriceGrid(
        reference_price=10.0,
        step_pct=0.01,
        grid_version=GRID_VERSION,
    )
    engine = DailyMigrationEngine(
        grid=grid,
        seller_model=seller_model,
        model_version=f"{MODEL_VERSION_PREFIX}-{seller_model.value}",
    )
    current = _initial(symbol, seller_model)
    float_shares = 100.0
    snapshot_ids: list[str] = []
    executed: list[float] = []
    conservation_errors: list[float] = []

    for offset, day in enumerate(range(6, 11)):
        events: tuple[InventoryEvent, ...] = ()
        if symbol == SYMBOLS[0] and day == 8:
            events = (
                InventoryEvent(
                    event_id=f"split-{symbol}-{day}",
                    kind=InventoryEventKind.SPLIT,
                    effective_at=_time(day, 9),
                    available_at=_time(day - 1),
                    snapshot_id=f"corp-split-{symbol}-{day}",
                    share_ratio=2.0,
                ),
            )
            float_shares = 200.0
        elif symbol == SYMBOLS[1] and day == 9:
            events = (
                InventoryEvent(
                    event_id=f"cash-{symbol}-{day}",
                    kind=InventoryEventKind.CASH_DIVIDEND,
                    effective_at=_time(day, 9),
                    available_at=_time(day - 1),
                    snapshot_id=f"corp-cash-{symbol}-{day}",
                    cash_per_share=0.2,
                ),
            )

        suspended = int(symbol[:6]) % 7 == 0 and day == 8
        bars: tuple[MinuteBar, ...] = ()
        if not suspended:
            timestamp = _time(day, 10)
            price = 10.0 + offset * 0.02
            bars = (
                MinuteBar(
                    timestamp=timestamp,
                    available_at=timestamp,
                    snapshot_id=f"minute-{symbol}-{day}",
                    open=price,
                    high=price,
                    low=price,
                    close=price,
                    volume_shares=10.0,
                    vwap=price,
                ),
            )
        result = engine.advance_day(
            previous_post=current,
            decision_at=_time(day),
            available_at=_time(day),
            minute_bars=bars,
            inventory_events=events,
            expected_free_float_shares=float_shares,
        )
        assert result.transition.same_day_resale_shares == 0.0
        current = result.post_snapshot
        snapshot_ids.append(current.snapshot_id)
        executed.append(result.transition.executed_sell_shares)
        conservation_errors.append(current.conservation_error)

    return (
        symbol,
        seller_model.value,
        tuple(snapshot_ids),
        tuple(executed),
        tuple(conservation_errors),
        current.free_float_shares,
        current.inventory.total_shares,
        current.inventory.unknown_cost_shares,
    )


def test_twenty_stock_week_is_t_plus_one_conserving_and_multiprocess_stable() -> None:
    payloads = tuple(
        (symbol, seller_model.value)
        for symbol in SYMBOLS
        for seller_model in SellerModel
    )
    serial = tuple(_run_symbol_model(payload) for payload in payloads)
    worker_count = min(10, os.cpu_count() or 1)
    with ProcessPoolExecutor(max_workers=worker_count) as pool:
        parallel = tuple(pool.map(_run_symbol_model, payloads))

    assert parallel == serial
    for row in serial:
        symbol = str(row[0])
        executed = row[3]
        errors = row[4]
        final_float = float(row[5])
        final_total = float(row[6])
        final_unknown = float(row[7])
        assert isinstance(executed, tuple)
        assert isinstance(errors, tuple)
        assert all(value == pytest.approx(0.0) for value in errors)
        assert final_total == pytest.approx(final_float)
        if int(symbol[:6]) % 7 == 0:
            assert executed[2] == 0.0
        if symbol == SYMBOLS[0]:
            assert final_float == 200.0
        if symbol not in SYMBOLS[:2]:
            assert 0.0 < final_unknown < 100.0
