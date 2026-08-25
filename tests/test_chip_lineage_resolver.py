from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from cyq_game.chip import (
    ChipSnapshotV2,
    DailyMigrationEngine,
    InventoryCell,
    MinuteBar,
    OriginSurvivalTransition,
    SellerModel,
    SnapshotPhase,
    SparseChipInventory,
    StableLogPriceGrid,
    TurnoverSensitivity,
)
from cyq_game.chip.ensemble_v2 import SELLER_MODEL_ORDER
from cyq_game.chip.migration_v2 import NONPOSITIVE_ECONOMIC_BUCKET
from cyq_game.strategy.chip_lineage import (
    _OPERATOR_GRID,
    ChipLineageResolver,
    PersistedChipLineageResolver,
    _aged_local_id,
    _pack_local_id,
)
from cyq_game.strategy.markup_retest import (
    ChipMassMethod,
    ChipMassProfile,
    LifecycleAnchor,
    LifecycleObservation,
    exact_anchor_retention,
)

GRID_VERSION = "lineage-grid-v1"
SYMBOL = "000001.SZ"


def _time(day: int, hour: int = 15) -> datetime:
    return datetime(2020, 1, day, hour, tzinfo=UTC)


def _initial(model: SellerModel) -> ChipSnapshotV2:
    grid = StableLogPriceGrid(10.0, 0.01, GRID_VERSION)
    cell = InventoryCell.create(
        cost_bucket_id=grid.bucket_for_price(10.0),
        holding_days=20,
        sensitivity=TurnoverSensitivity.NEUTRAL,
        acquisition_cost=10.0,
        economic_break_even=10.0,
        shares=100.0,
    )
    return ChipSnapshotV2(
        symbol=SYMBOL,
        trading_date=_time(3).date(),
        decision_at=_time(3),
        effective_at=_time(3),
        available_at=_time(3),
        phase=SnapshotPhase.POST,
        snapshot_id=f"lineage-initial-{model.value}",
        model_version=f"lineage-model-{model.value}",
        grid_version=GRID_VERSION,
        seller_model=model,
        inventory=SparseChipInventory.canonical((cell,)),
        free_float_shares=100.0,
        latent_supply_shares=0.0,
        input_snapshot_ids=("daily", "float"),
        pit_grade="A",
        hard_valid=True,
    )


def _history(
    models: tuple[SellerModel, ...] = SELLER_MODEL_ORDER,
) -> tuple[tuple[ChipSnapshotV2, ...], tuple[OriginSurvivalTransition, ...]]:
    snapshots: list[ChipSnapshotV2] = []
    transitions: list[OriginSurvivalTransition] = []
    for model in models:
        current = _initial(model)
        snapshots.append(current)
        engine = DailyMigrationEngine(
            grid=StableLogPriceGrid(10.0, 0.01, GRID_VERSION),
            seller_model=model,
            model_version=current.model_version,
        )
        for day, price in ((6, 10.0), (7, 10.1)):
            timestamp = _time(day, 10)
            bar = MinuteBar(
                timestamp=timestamp,
                available_at=timestamp,
                snapshot_id=f"minute-{model.value}-{day}",
                open=price,
                high=price,
                low=price,
                close=price,
                volume_shares=10.0,
                vwap=price,
            )
            result = engine.advance_day(
                previous_post=current,
                decision_at=_time(day),
                available_at=_time(day),
                minute_bars=(bar,),
                inventory_events=(),
                expected_free_float_shares=100.0,
            )
            transitions.append(result.transition)
            current = result.post_snapshot
            snapshots.append(current)
    return tuple(snapshots), tuple(transitions)


def _anchor(anchor_id: str = "root-1") -> LifecycleAnchor:
    return LifecycleAnchor(
        anchor_id=anchor_id,
        symbol=SYMBOL,
        source_snapshot_id="strategy-panel-snapshot",
        root_anchor_id=anchor_id,
        parent_anchor_id=None,
        role="ROOT",
        created_at=_time(3).date(),
        lower=9.9,
        upper=10.1,
        reference_mass=1.0,
        average_cost=10.0,
        cost_p50=10.0,
        main_peak=10.0,
        band_width=0.2,
        peak_count=1,
        mass_method=ChipMassMethod.HISTOGRAM_EXACT,
    )


def _observation() -> LifecycleObservation:
    return LifecycleObservation(
        symbol=SYMBOL,
        decision_at=_time(7),
        available_at=_time(7),
        snapshot_ids=("strategy-panel-snapshot",),
        hard_valid=True,
        tradable=True,
        pit_grade="A",
        setup_score=0.8,
        breakout_excess_atr=0.5,
        support_regained=True,
        downside_absorption=True,
        chip_profile=ChipMassProfile.from_histogram((10.0,), (1.0,), mass_tolerance=1e-12),
        cost_p10=9.9,
        cost_p90=10.1,
        peak_count=1,
        recent_band_overlap=1.0,
        distribution_score=0.0,
        structure_support=9.8,
        close=10.1,
        close_vs_vwap=0.01,
        low=10.0,
        volume=10.0,
        turnover=0.1,
        average_cost=10.05,
        cost_p50=10.05,
        main_peak=10.0,
        prior_average_cost=10.0,
        prior_cost_p50=10.0,
        prior_main_peak=10.0,
        atr=1.0,
    )


def test_resolver_traces_three_models_once_and_reuses_exact_anchor_cache() -> None:
    snapshots, transitions = _history()
    resolver = ChipLineageResolver(snapshots, transitions)
    anchor = _anchor()
    observation = _observation()

    first = exact_anchor_retention(anchor, observation, resolver=resolver)
    second = exact_anchor_retention(anchor, observation, resolver=resolver)

    assert first is not None
    assert second is first
    assert tuple(model for model, _ in first.model_retentions) == SELLER_MODEL_ORDER
    assert 0.0 <= first.lower <= first.central <= first.upper <= 1.0
    assert resolver.cached_result_count == 1
    assert resolver.trace_cache_count == 3

    # A different parameter group may share the same root anchor, but a
    # genuinely different anchor identity must receive independent traces.
    third = resolver(_anchor("root-2"), observation)
    assert third is not None
    assert resolver.cached_result_count == 2
    assert resolver.trace_cache_count == 6


def test_resolver_fails_closed_when_one_model_or_pit_snapshot_is_missing() -> None:
    two_models = (SellerModel.UNIFORM, SellerModel.DISPOSITION)
    snapshots, transitions = _history(two_models)
    assert ChipLineageResolver(snapshots, transitions)(_anchor(), _observation()) is None

    full_snapshots, full_transitions = _history()
    future_snapshots = tuple(
        replace(snapshot, available_at=_time(7, 16), decision_at=_time(7, 16))
        if snapshot.trading_date == _time(7).date()
        else snapshot
        for snapshot in full_snapshots
    )
    assert (
        ChipLineageResolver(future_snapshots, full_transitions)(_anchor(), _observation()) is None
    )


def test_root_anchor_identity_cannot_be_reused_for_another_symbol() -> None:
    snapshots, transitions = _history()
    resolver = ChipLineageResolver(snapshots, transitions)
    assert resolver(_anchor(), _observation()) is not None

    with pytest.raises(ValueError, match="anchor symbol"):
        resolver(_anchor(), replace(_observation(), symbol="000002.SZ"))


def test_persisted_operator_resolver_traces_anchor_without_counting_new_chips(
    tmp_path,
) -> None:
    price_bucket = _OPERATOR_GRID.bucket_for_price(10.0)
    anchor_price = _OPERATOR_GRID.price_for_bucket(price_bucket)
    source_id = _pack_local_id(price_bucket, 20, 1)
    new_chip_id = _pack_local_id(price_bucket + 2, 0, 1)
    model_retentions = {
        SellerModel.UNIFORM: 0.5,
        SellerModel.DISPOSITION: 0.6,
        SellerModel.ACTIVE_STICKY: 0.7,
    }
    rows = []
    for model, retention in model_retentions.items():
        common = {
            "storage_version": "chip-operator-log-v8",
            "symbol": SYMBOL,
            "seller_model": model.value,
            "source_cell_ids_override": [],
            "destination_override_positions": [],
            "destination_override_cell_ids": [],
            "retention_codes": b"",
        }
        rows.append(
            {
                **common,
                "trade_date": _time(3).date(),
                "available_at": _time(3),
                "free_float_shares": 100.0,
                "checkpoint_local_ids": [source_id],
                "checkpoint_shares": [100.0],
                "retention_encoding": 0,
                "retention_values": [],
                "inventory_adjustment_local_ids": [],
                "inventory_adjustment_shares": [],
            }
        )
        rows.append(
            {
                **common,
                "trade_date": _time(6).date(),
                "available_at": _time(6),
                "free_float_shares": 100.0,
                "checkpoint_local_ids": [],
                "checkpoint_shares": [],
                "retention_encoding": 0,
                "retention_values": [retention],
                # Sold anchor chips become genuinely new chips.  They restore
                # inventory mass but must never restore anchor bloodline mass.
                "inventory_adjustment_local_ids": [new_chip_id],
                "inventory_adjustment_shares": [100.0 * (1.0 - retention)],
            }
        )

    path = tmp_path / "parts" / "bucket=0" / "000001_SZ.parquet"
    path.parent.mkdir(parents=True)
    pq.write_table(pa.Table.from_pylist(rows), path)
    resolver = PersistedChipLineageResolver(tmp_path)
    anchor = replace(
        _anchor(),
        lower=anchor_price - 1e-6,
        upper=anchor_price + 1e-6,
    )
    observation = replace(_observation(), decision_at=_time(6), available_at=_time(6))

    first = resolver(anchor, observation)
    second = resolver(anchor, observation)

    assert first is not None
    assert second is first
    assert first.lower == pytest.approx(0.5)
    assert first.central == pytest.approx(0.6)
    assert first.upper == pytest.approx(0.7)
    assert resolver.cached_result_count == 1
    assert resolver.loaded_symbol_count == 1
    assert resolver.cached_operator_step_count == 3

    second_anchor = replace(
        anchor,
        anchor_id="root-2",
        root_anchor_id="root-2",
    )
    second_anchor_result = resolver(second_anchor, observation)
    assert second_anchor_result is not None
    assert second_anchor_result.model_retentions == first.model_retentions
    assert second_anchor_result.central == first.central
    assert resolver.cached_operator_step_count == 3

    resolver.release_symbol(SYMBOL)

    assert resolver.cached_result_count == 0
    assert resolver.loaded_symbol_count == 0
    assert resolver.cached_operator_step_count == 0
    reloaded = resolver(anchor, observation)
    assert reloaded == first
    assert reloaded is not first


def test_v10_resolver_uses_economic_cost_and_replays_checkpoint_across_years(
    tmp_path,
) -> None:
    acquisition_bucket = _OPERATOR_GRID.bucket_for_price(10.0)
    economic_bucket = _OPERATOR_GRID.bucket_for_price(9.5)
    anchor_price = _OPERATOR_GRID.price_for_bucket(economic_bucket)
    source_id = _pack_local_id(acquisition_bucket, 20, 1)
    aged_id = _aged_local_id(source_id)
    new_chip_id = _pack_local_id(acquisition_bucket + 2, 0, 1)
    model_retentions = {
        SellerModel.UNIFORM: 0.5,
        SellerModel.DISPOSITION: 0.6,
        SellerModel.ACTIVE_STICKY: 0.7,
    }
    anchor_date = datetime(2019, 12, 30, 15, tzinfo=UTC)
    observation_date = datetime(2020, 1, 2, 15, tzinfo=UTC)

    rows_by_year: dict[int, list[dict[str, object]]] = {2019: [], 2020: []}
    for model, retention in model_retentions.items():
        common = {
            "storage_version": "chip-operator-log-v10",
            "symbol": SYMBOL,
            "seller_model": model.value,
            "source_cell_ids_override": [],
            "destination_override_positions": [],
            "destination_override_cell_ids": [],
            "retention_codes": b"",
            "cash_dividend_per_share": 0.0,
            "share_multiplier": 1.0,
        }
        rows_by_year[2019].append(
            {
                **common,
                "trade_date": anchor_date.date(),
                "available_at": anchor_date,
                "free_float_shares": 100.0,
                "checkpoint_local_ids": [source_id],
                "checkpoint_shares": [100.0],
                # The immutable cell identity still says 10.0, but a prior
                # dividend has moved its economic break-even to 9.5.
                "checkpoint_economic_bucket_ids": [economic_bucket],
                "retention_encoding": 0,
                "retention_values": [],
                "inventory_adjustment_local_ids": [],
                "inventory_adjustment_shares": [],
                "inventory_adjustment_economic_bucket_ids": [],
            }
        )
        rows_by_year[2020].append(
            {
                **common,
                "trade_date": observation_date.date(),
                "available_at": observation_date,
                "free_float_shares": 100.0,
                # This is also a checkpoint, but its transition must remain
                # present so a 2019 anchor can be replayed into 2020.
                "checkpoint_local_ids": [aged_id, new_chip_id],
                "checkpoint_shares": [
                    100.0 * retention,
                    100.0 * (1.0 - retention),
                ],
                "checkpoint_economic_bucket_ids": [
                    economic_bucket,
                    acquisition_bucket + 2,
                ],
                "retention_encoding": 0,
                "retention_values": [retention],
                "inventory_adjustment_local_ids": [new_chip_id],
                "inventory_adjustment_shares": [100.0 * (1.0 - retention)],
                "inventory_adjustment_economic_bucket_ids": [
                    acquisition_bucket + 2
                ],
            }
        )

    for year, rows in rows_by_year.items():
        path = (
            tmp_path
            / f"year={year}"
            / "parts"
            / "bucket=0"
            / "000001_SZ.parquet"
        )
        path.parent.mkdir(parents=True)
        pq.write_table(pa.Table.from_pylist(rows), path)

    resolver = PersistedChipLineageResolver(tmp_path)
    anchor = replace(
        _anchor(),
        created_at=anchor_date.date(),
        lower=anchor_price - 1e-6,
        upper=anchor_price + 1e-6,
    )
    observation = replace(
        _observation(),
        decision_at=observation_date,
        available_at=observation_date,
    )

    # A short first request must not freeze the symbol cache at 2019.  The
    # following cross-year request incrementally loads the 2020 partition.
    anchor_day_result = resolver(
        anchor,
        replace(
            observation,
            decision_at=anchor_date,
            available_at=anchor_date,
        ),
    )
    result = resolver(anchor, observation)

    assert anchor_day_result is not None
    assert anchor_day_result.central == pytest.approx(1.0)
    assert result is not None
    assert result.lower == pytest.approx(0.5)
    assert result.central == pytest.approx(0.6)
    assert result.upper == pytest.approx(0.7)


def test_persisted_replay_keeps_nonpositive_economic_break_even() -> None:
    source_bucket = _OPERATOR_GRID.bucket_for_price(0.25)
    source_id = _pack_local_id(source_bucket, 20, 1)
    destination_id = _aged_local_id(source_id)
    row = {
        "cash_dividend_per_share": 0.5,
        "share_multiplier": 1.0,
        "source_cell_ids_override": [],
        "destination_override_positions": [],
        "destination_override_cell_ids": [],
        "retention_encoding": 0,
        "retention_values": [1.0],
        "retention_codes": b"",
        "inventory_adjustment_local_ids": [],
        "inventory_adjustment_shares": [],
        "inventory_adjustment_economic_bucket_ids": [],
        "free_float_shares": 100.0,
    }

    inventory, lineage, economic = PersistedChipLineageResolver._advance(
        {source_id: 100.0},
        {source_id: 100.0},
        {source_id: source_bucket},
        row,
    )

    assert inventory == {destination_id: 100.0}
    assert lineage == {destination_id: 100.0}
    assert economic == {destination_id: NONPOSITIVE_ECONOMIC_BUCKET}
