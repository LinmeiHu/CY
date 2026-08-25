from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime

import numpy as np
import pytest

from cyq_game.chip import (
    AnchorCandidateRef,
    AnchorRole,
    AnchorTraceCache,
    AnchorTraceCacheKey,
    ChipSnapshotV2,
    ChipStateContractError,
    DailyMigrationEngine,
    DailyMigrationResult,
    InventoryCell,
    InventoryEvent,
    InventoryEventKind,
    LifecycleAnchorRef,
    MinuteBar,
    OriginTracer,
    SellerModel,
    SnapshotPhase,
    SparseChipInventory,
    StableLogPriceGrid,
    SupportAnchorEvidence,
    SupportAnchorPolicy,
    TurnoverSensitivity,
    initial_unknown_snapshot,
    prepare_minute_path,
)

MODEL_VERSION = "chip-state-v2-test"
GRID_VERSION = "log-grid-v1-test"


def _time(day: int, hour: int = 15, minute: int = 0) -> datetime:
    return datetime(2020, 1, day, hour, minute, tzinfo=UTC)


def _known_snapshot(
    *,
    snapshot_id: str,
    day: int,
    shares: float = 100.0,
    acquisition_cost: float = 10.0,
    economic_break_even: float | None = None,
    seller_model: SellerModel = SellerModel.UNIFORM,
) -> ChipSnapshotV2:
    grid = StableLogPriceGrid(
        reference_price=10.0,
        step_pct=0.01,
        grid_version=GRID_VERSION,
    )
    cell = InventoryCell.create(
        cost_bucket_id=grid.bucket_for_price(acquisition_cost),
        holding_days=20,
        sensitivity=TurnoverSensitivity.NEUTRAL,
        acquisition_cost=acquisition_cost,
        economic_break_even=(
            acquisition_cost
            if economic_break_even is None
            else economic_break_even
        ),
        shares=shares,
    )
    decision_at = _time(day)
    return ChipSnapshotV2(
        symbol="000001.SZ",
        trading_date=decision_at.date(),
        decision_at=decision_at,
        effective_at=decision_at,
        available_at=decision_at,
        phase=SnapshotPhase.POST,
        snapshot_id=snapshot_id,
        model_version=MODEL_VERSION,
        grid_version=GRID_VERSION,
        seller_model=seller_model,
        inventory=SparseChipInventory.canonical((cell,)),
        free_float_shares=shares,
        latent_supply_shares=0.0,
        input_snapshot_ids=("daily-test", "float-test"),
        pit_grade="A",
        hard_valid=True,
    )


def _engine(seller_model: SellerModel = SellerModel.UNIFORM) -> DailyMigrationEngine:
    return DailyMigrationEngine(
        grid=StableLogPriceGrid(
            reference_price=10.0,
            step_pct=0.01,
            grid_version=GRID_VERSION,
        ),
        seller_model=seller_model,
        model_version=MODEL_VERSION,
    )


def _bar(*, day: int, volume: float, price: float = 10.0) -> MinuteBar:
    timestamp = _time(day, 10)
    return MinuteBar(
        timestamp=timestamp,
        available_at=timestamp,
        snapshot_id=f"minute-{day}",
        open=price,
        high=price,
        low=price,
        close=price,
        volume_shares=volume,
        vwap=price,
    )


def _advance(
    previous: ChipSnapshotV2,
    *,
    day: int,
    volume: float = 0.0,
    price: float = 10.0,
    events: tuple[InventoryEvent, ...] = (),
    expected_float: float | None = None,
) -> DailyMigrationResult:
    bars = () if volume == 0 else (_bar(day=day, volume=volume, price=price),)
    return _engine(previous.seller_model).advance_day(
        previous_post=previous,
        decision_at=_time(day),
        available_at=_time(day),
        minute_bars=bars,
        inventory_events=events,
        expected_free_float_shares=(
            previous.free_float_shares if expected_float is None else expected_float
        ),
    )


@pytest.mark.parametrize("seller_model", tuple(SellerModel))
def test_prepared_minute_path_is_exactly_equivalent(seller_model: SellerModel) -> None:
    previous = _known_snapshot(
        snapshot_id=f"previous-{seller_model}",
        day=2,
        shares=1_000.0,
        seller_model=seller_model,
    )
    bars = tuple(
        replace(
            _bar(day=3, volume=volume, price=price),
            timestamp=_time(3, 10, minute),
            available_at=_time(3, 10, minute),
            snapshot_id=f"minute-3-{minute}",
        )
        for minute, volume, price in (
            (0, 20.0, 9.9),
            (1, 30.0, 10.1),
            (2, 10.0, 10.0),
        )
    )
    engine = _engine(seller_model)
    direct = engine.advance_day(
        previous_post=previous,
        decision_at=_time(3),
        available_at=_time(3),
        minute_bars=bars,
        inventory_events=(),
        expected_free_float_shares=1_000.0,
    )
    prepared = prepare_minute_path(
        grid=engine.grid,
        decision_at=_time(3),
        minute_bars=bars,
    )
    shared = engine.advance_day(
        previous_post=previous,
        decision_at=_time(3),
        available_at=_time(3),
        minute_bars=None,
        inventory_events=(),
        expected_free_float_shares=1_000.0,
        prepared_minute_path=prepared,
    )

    assert shared == direct


@pytest.mark.parametrize("seller_model", tuple(SellerModel))
def test_packed_warmup_reuses_previous_state_without_changing_results(
    seller_model: SellerModel,
) -> None:
    previous = _known_snapshot(
        snapshot_id=f"packed-previous-{seller_model}",
        day=2,
        shares=1_000.0,
        seller_model=seller_model,
    )
    slow_engine = _engine(seller_model)
    fast_engine = _engine(seller_model)
    slow_state = previous
    fast_state = previous

    for day, observations in (
        (3, ((0, 20.0, 9.9), (1, 30.0, 10.1), (2, 10.0, 10.0))),
        (4, ((0, 40.0, 10.2), (1, 25.0, 10.0), (2, 15.0, 10.1))),
    ):
        bars = tuple(
            replace(
                _bar(day=day, volume=volume, price=price),
                timestamp=_time(day, 10, minute),
                available_at=_time(day, 10, minute),
                snapshot_id=f"packed-minute-{day}-{minute}",
            )
            for minute, volume, price in observations
        )
        prepared_slow = prepare_minute_path(
            grid=slow_engine.grid,
            decision_at=_time(day),
            minute_bars=bars,
        )
        prepared_fast = prepare_minute_path(
            grid=fast_engine.grid,
            decision_at=_time(day),
            minute_bars=bars,
        )
        slow_state = slow_engine.advance_warmup_day(
            previous_post=slow_state,
            decision_at=_time(day),
            available_at=_time(day),
            inventory_events=(),
            expected_free_float_shares=1_000.0,
            additional_input_snapshot_ids=(f"daily-{day}", f"float-{day}"),
            input_hard_valid=True,
            input_quality_reason_codes=(),
            prepared_minute_path=prepared_slow,
            build_transition=True,
        )
        fast_state = fast_engine.advance_packed_warmup_day(
            previous_post=fast_state,
            decision_at=_time(day),
            available_at=_time(day),
            inventory_events=(),
            expected_free_float_shares=1_000.0,
            additional_input_snapshot_ids=(f"daily-{day}", f"float-{day}"),
            input_hard_valid=True,
            input_quality_reason_codes=(),
            prepared_minute_path=prepared_fast,
            build_transition=True,
        )

        assert fast_state.to_snapshot() == slow_state.to_snapshot()
        assert fast_state.last_transition == slow_state.last_transition


def test_same_price_band_replacement_is_not_anchor_lineage_retention() -> None:
    anchor = _known_snapshot(snapshot_id="anchor-post", day=2)
    tracer = OriginTracer.from_snapshot(anchor_id="anchor-1", snapshot=anchor)

    result = _advance(anchor, day=3, volume=75.0, price=10.0)
    advanced = tracer.advance(result.transition)

    # The cost band is again fully occupied after same-price purchases, but only
    # 25% of the causally frozen anchor inventory survived.
    assert result.post_snapshot.inventory.total_shares == pytest.approx(100.0)
    assert advanced.retention == pytest.approx(0.25)


def test_minute_path_uses_only_fixed_pre_inventory_under_t_plus_one() -> None:
    previous = _known_snapshot(snapshot_id="post-2", day=2)
    result = _advance(previous, day=3, volume=100.0)

    assert result.transition.fixed_pre_eligible_shares == pytest.approx(100.0)
    assert result.transition.executed_sell_shares == pytest.approx(100.0)
    assert result.transition.same_day_resale_shares == 0.0
    assert result.post_snapshot.inventory.total_shares == pytest.approx(100.0)

    with pytest.raises(ChipStateContractError, match=r"PRE eligible|volume"):
        _advance(previous, day=3, volume=100.01)


def test_vector_residual_cannot_create_source_lineage() -> None:
    values = np.asarray([1e-12, 1e16, 3.0], dtype=float)
    upper_bounds = values.copy()
    target = float(values.sum()) - 1.0

    DailyMigrationEngine._bridge_residual_with_bounds(
        values,
        target=target,
        upper_bounds=upper_bounds,
    )

    assert np.all(values >= 0.0)
    assert np.all(values <= upper_bounds)
    assert float(values.sum()) == pytest.approx(target)


def test_fast_minute_depletion_matches_exact_sequential_water_fill() -> None:
    rng = np.random.default_rng(20200822)
    original = rng.uniform(1e5, 1e8, size=200)
    exact = original.copy()
    fast = original.copy()
    volumes = rng.uniform(0.0, original.sum() * 0.0002, size=240)

    for minute, volume in enumerate(volumes):
        hazards = np.exp(
            np.clip(
                rng.normal(loc=minute / 2400, scale=0.4, size=original.size),
                -2.0,
                2.0,
            )
        )
        DailyMigrationEngine._deplete_vector(exact, float(volume), hazards)
        DailyMigrationEngine._deplete_vector_fast(fast, float(volume), hazards)

    target = float(original.sum()) - float(volumes.sum())
    DailyMigrationEngine._bridge_residual_with_bounds(
        fast,
        target=target,
        upper_bounds=original,
    )

    assert float(fast.sum()) == pytest.approx(target, rel=0, abs=1e-5)
    assert np.allclose(fast, exact, rtol=1e-12, atol=1e-5)


@pytest.mark.parametrize(
    ("kind", "issue_price"),
    [
        (InventoryEventKind.FLOAT_ADD_KNOWN, 10.0),
        (InventoryEventKind.FLOAT_ADD_UNKNOWN, None),
    ],
)
def test_same_day_float_addition_is_not_a_t_plus_one_seller(
    kind: InventoryEventKind,
    issue_price: float | None,
) -> None:
    previous = _known_snapshot(snapshot_id="post-2", day=2)
    addition = InventoryEvent(
        event_id=f"add-{kind.value}",
        kind=kind,
        effective_at=_time(3, 9),
        available_at=_time(2),
        snapshot_id=f"float-{kind.value}",
        shares=50.0,
        issue_price=issue_price,
    )

    result = _advance(
        previous,
        day=3,
        volume=100.0,
        events=(addition,),
        expected_float=150.0,
    )
    assert result.transition.fixed_pre_eligible_shares == pytest.approx(100.0)
    assert result.transition.executed_sell_shares == pytest.approx(100.0)
    assert result.post_snapshot.inventory.total_shares == pytest.approx(150.0)

    with pytest.raises(ChipStateContractError, match=r"PRE seller pool"):
        _advance(
            previous,
            day=3,
            volume=100.01,
            events=(addition,),
            expected_float=150.0,
        )


def test_unknown_cost_is_not_invented_and_real_trading_replaces_it() -> None:
    initial = initial_unknown_snapshot(
        symbol="000001.SZ",
        decision_at=_time(2),
        available_at=_time(2),
        free_float_shares=100.0,
        latent_supply_shares=0.0,
        seller_model=SellerModel.UNIFORM,
        model_version=MODEL_VERSION,
        grid_version=GRID_VERSION,
        input_snapshot_ids=("daily-test", "float-test"),
    )

    assert initial.inventory.unknown_cost_shares == pytest.approx(100.0)
    assert not initial.hard_valid
    with pytest.raises(ChipStateContractError, match="UNKNOWN_COST"):
        replace(initial, hard_valid=True)

    result = _advance(initial, day=3, volume=100.0)
    assert result.post_snapshot.inventory.unknown_cost_shares == pytest.approx(0.0)
    assert result.post_snapshot.inventory.known_cost_shares == pytest.approx(100.0)
    assert result.transition.same_day_resale_shares == 0.0


def test_cash_dividend_and_split_use_one_price_coordinate_and_conserve() -> None:
    previous = _known_snapshot(
        snapshot_id="post-2",
        day=2,
        acquisition_cost=10.0,
        economic_break_even=10.0,
    )
    cash = InventoryEvent(
        event_id="cash-3",
        kind=InventoryEventKind.CASH_DIVIDEND,
        effective_at=_time(3, 9),
        available_at=_time(2),
        snapshot_id="corp-cash-3",
        cash_per_share=0.5,
    )
    after_cash = _advance(previous, day=3, events=(cash,))
    cash_cell = after_cash.post_snapshot.inventory.cells[0]
    assert cash_cell.acquisition_cost == pytest.approx(10.0)
    assert cash_cell.economic_break_even == pytest.approx(9.5)
    assert after_cash.post_snapshot.conservation_error == pytest.approx(0.0)

    tracer = OriginTracer.from_snapshot(anchor_id="pre-split-anchor", snapshot=previous)
    split = InventoryEvent(
        event_id="split-3",
        kind=InventoryEventKind.SPLIT,
        effective_at=_time(3, 9),
        available_at=_time(2),
        snapshot_id="corp-split-3",
        share_ratio=2.0,
    )
    after_split = _advance(
        previous,
        day=3,
        events=(split,),
        expected_float=200.0,
    )
    split_cell = after_split.post_snapshot.inventory.cells[0]
    assert split_cell.shares == pytest.approx(200.0)
    assert split_cell.acquisition_cost == pytest.approx(5.0)
    assert split_cell.economic_break_even == pytest.approx(5.0)
    assert after_split.post_snapshot.conservation_error == pytest.approx(0.0)
    assert tracer.advance(after_split.transition).retention == pytest.approx(1.0)


def test_suspension_is_identity_for_anchor_lineage() -> None:
    anchor = _known_snapshot(snapshot_id="post-2", day=2)
    tracer = OriginTracer.from_snapshot(anchor_id="anchor-suspended", snapshot=anchor)
    result = _advance(anchor, day=3)

    assert result.transition.executed_sell_shares == 0.0
    assert tracer.advance(result.transition).retention == pytest.approx(1.0)
    assert result.post_snapshot.inventory.total_shares == pytest.approx(100.0)


@pytest.mark.parametrize("timestamp_field", ["effective_at", "available_at"])
def test_snapshot_rejects_information_after_decision(timestamp_field: str) -> None:
    snapshot = _known_snapshot(snapshot_id="post-2", day=2)
    with pytest.raises(ChipStateContractError, match="decision_at"):
        if timestamp_field == "effective_at":
            replace(snapshot, effective_at=_time(3))
        else:
            replace(snapshot, available_at=_time(3))


def test_snapshot_rejects_supply_conservation_gap() -> None:
    snapshot = _known_snapshot(snapshot_id="post-2", day=2)
    with pytest.raises(ChipStateContractError, match="conservation"):
        replace(snapshot, free_float_shares=101.0)


def test_dual_anchor_chain_requires_causal_controlled_support_update() -> None:
    root_snapshot = _known_snapshot(snapshot_id="root-post", day=2)
    candidate = AnchorCandidateRef.from_snapshot(
        root_snapshot,
        selection_rule_version="setup-v1",
    )
    root = LifecycleAnchorRef.confirm_root(candidate, confirmed_at=_time(3))
    support_snapshot = _advance(root_snapshot, day=4, volume=10.0).post_snapshot
    evidence = SupportAnchorEvidence.create(
        evaluated_at=_time(4),
        root_anchor_id=root.anchor_id,
        source_snapshot_id=support_snapshot.snapshot_id,
        root_origin_retention=0.90,
        cost_migration_atr=0.25,
        concentration_change=0.0,
        peak_split=False,
        structure_broken=False,
        input_snapshot_ids=(support_snapshot.snapshot_id,),
    )
    policy = SupportAnchorPolicy(
        min_root_origin_retention=0.70,
        min_cost_migration_atr=0.0,
        max_cost_migration_atr=0.5,
        max_concentration_deterioration=0.1,
        policy_version="support-v1",
    )
    support = LifecycleAnchorRef.create_support(
        root=root,
        parent=root,
        snapshot=support_snapshot,
        confirmed_at=_time(4),
        evidence=evidence,
        policy=policy,
    )

    assert root.role is AnchorRole.ROOT
    assert root.parent_anchor_id is None
    assert support.role is AnchorRole.SUPPORT
    assert support.root_anchor_id == root.anchor_id
    assert support.parent_anchor_id == root.anchor_id

    weak = replace(evidence, root_origin_retention=0.50)
    with pytest.raises(ChipStateContractError, match="ROOT_ORIGIN_RETENTION_TOO_LOW"):
        LifecycleAnchorRef.create_support(
            root=root,
            parent=root,
            snapshot=support_snapshot,
            confirmed_at=_time(4),
            evidence=weak,
            policy=policy,
        )


def test_anchor_trace_cache_is_versioned_and_append_only() -> None:
    snapshot = _known_snapshot(snapshot_id="post-2", day=2)
    tracer = OriginTracer.from_snapshot(anchor_id="anchor-cache", snapshot=snapshot)
    key = AnchorTraceCacheKey(
        symbol=snapshot.symbol,
        anchor_date=snapshot.trading_date,
        current_date=snapshot.trading_date,
        model_version=snapshot.model_version,
    )
    cache = AnchorTraceCache()
    cache.put(key, tracer)
    cache.put(key, tracer)

    assert cache.get(key) == tracer
    assert len(cache) == 1
    with pytest.raises(ChipStateContractError, match="does not match"):
        cache.put(replace(key, model_version="another-model"), tracer)


def test_chip_state_objects_are_immutable() -> None:
    snapshot = _known_snapshot(snapshot_id="post-2", day=2)
    with pytest.raises(FrozenInstanceError):
        snapshot.snapshot_id = "mutated"  # type: ignore[misc]
