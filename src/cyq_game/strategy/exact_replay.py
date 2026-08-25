"""Single-pass exact-execution replay for a small parameter shortlist.

The development panel and persisted chip lineage are the expensive inputs.  A
shortlisted exit grid therefore shares one predictor scan, one observation and
one lineage resolver across all parameter combinations.  Each combination
still owns independent lifecycle, pending-order and position state.

Execution results are scheduled from registered five-minute windows but may
only affect lifecycle state on their actual future trading date.  This keeps
the fast research replay causal while avoiding one complete panel scan per
parameter.
"""

from __future__ import annotations

import itertools
import os
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

import duckdb
import numpy as np

from cyq_game.domain import ExitReason
from cyq_game.strategy.chip_lineage import StreamingLineageSession
from cyq_game.strategy.execution import (
    EntryExecution,
    EntryExecutionStatus,
    ExecutionScope,
    ExecutionWindow,
    ExitExecution,
    ExitExecutionStatus,
    ExitIntent,
    execute_entry,
    execute_exit,
)
from cyq_game.strategy.markup_retest import (
    AnchorRetentionResolver,
    LifecycleMachine,
    LifecycleMemory,
    LifecycleObservation,
    MarkupRetestConfig,
    StrategyParameters,
    StrategySignal,
    StrategyStage,
    chip_structure_broken,
    distribution_score_with_anchor,
    exact_anchor_retention,
    load_passing_frozen_parameters,
    rebase_lifecycle_memory,
)
from cyq_game.strategy.research import (
    _ACTIVE,
    _BROKEN,
    _NEUTRAL,
    _advance_entries,
    _clear_anchor_state,
    _empty_anchors,
    _empty_objects,
    _lifecycle_anchor,
    _rebase_lattice_for_action,
)
from cyq_game.strategy.signals import (
    observation_from_record,
    serialize_signal,
    stream_panel,
)

CN_TZ = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class ExactReplayResult:
    """Deterministic event-study output for one shared predictor scan."""

    parameters: tuple[StrategyParameters, ...]
    input_rows: int
    evaluation_rows: int
    panel_passes: int
    signals: tuple[dict[str, Any], ...]
    trades: tuple[dict[str, Any], ...]
    open_exposures: tuple[dict[str, Any], ...]


@dataclass
class _Position:
    signal: StrategySignal
    entry: EntryExecution
    is_evaluation: bool
    quantity: int
    dividends: float = 0.0
    action_snapshots: list[str] = field(default_factory=list)


@dataclass
class _PendingEntry:
    signal: StrategySignal
    execution: EntryExecution
    is_evaluation: bool


@dataclass
class _PendingExit:
    intent: ExitIntent
    execution: ExitExecution


@dataclass
class _ParameterState:
    memory: LifecycleMemory = field(default_factory=LifecycleMemory)
    position: _Position | None = None
    pending_entry: _PendingEntry | None = None
    pending_exit: _PendingExit | None = None


def evaluate_exact_parameter_lattice_symbol(
    records: Iterable[Mapping[str, object]],
    windows: Sequence[ExecutionWindow],
    market_trading_dates: Sequence[date],
    config: MarkupRetestConfig,
    parameters: Sequence[StrategyParameters],
    *,
    panel_snapshot_id: str = "panel-in-memory",
    anchor_retention_resolver: AnchorRetentionResolver | None = None,
) -> ExactReplayResult:
    """Replay one complete symbol for every shortlisted parameter.

    The function deliberately uses the canonical scalar ``LifecycleMachine``
    for transition semantics.  Its acceleration comes from sharing the panel
    scan, observation conversion, exact lineage cache and execution windows;
    it never creates an alternative strategy definition.
    """

    selected = tuple(parameters)
    _validate_parameters(selected)
    machines = tuple(
        LifecycleMachine(
            config,
            item,
            anchor_retention_resolver=anchor_retention_resolver,
        )
        for item in selected
    )
    states = [_ParameterState() for _ in selected]
    raw_records = [dict(record) for record in records]
    first_broken_date = _first_action_coordinate_mismatch(raw_records)
    ordered_windows = tuple(
        sorted(windows, key=lambda item: (item.trade_date, item.window_index, item.available_at))
    )
    if first_broken_date is not None:
        ordered_windows = tuple(
            replace(window, corporate_action_blocking=True)
            if window.trade_date >= first_broken_date
            else window
            for window in ordered_windows
        )
    ordered_market_dates = tuple(sorted(dict.fromkeys(market_trading_dates)))
    signals: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    input_rows = 0
    evaluation_rows = 0
    trading_index = 0
    symbol: str | None = None
    previous_date: date | None = None
    previous_close: float | None = None
    action_coordinate_broken = False

    for raw_record in raw_records:
        record = dict(raw_record)
        mismatch = _action_coordinate_mismatch(record, previous_close)
        action_coordinate_broken = action_coordinate_broken or mismatch
        if action_coordinate_broken:
            reasons = [
                item
                for item in str(record.get("reason_codes") or "").split("|")
                if item
            ]
            reasons.append("ACTION_PRICE_COORDINATE_MISMATCH")
            record.update(
                {
                    "research_hard_valid": False,
                    "corporate_action_blocking": bool(
                        record.get("corporate_action_blocking")
                    )
                    or mismatch,
                    "share_multiplier": 1.0,
                    "cash_per_share": 0.0,
                    "reason_codes": "|".join(dict.fromkeys(reasons)),
                }
            )
        observation = observation_from_record(record, config, panel_snapshot_id)
        trade_date = _as_date(record.get("trade_date"), field="trade_date")
        if symbol is None:
            symbol = observation.symbol
        elif observation.symbol != symbol:
            raise ValueError(
                "exact symbol replay received multiple symbols: "
                f"{symbol}, {observation.symbol}"
            )
        if previous_date is not None and trade_date <= previous_date:
            raise ValueError(
                "exact symbol replay requires unique ordered dates: "
                f"previous={previous_date}, current={trade_date}"
            )
        previous_date = trade_date
        is_evaluation = bool(record.get("is_evaluation_row"))
        input_rows += 1
        evaluation_rows += int(is_evaluation)

        for machine, state, item in zip(machines, states, selected, strict=True):
            _advance_parameter(
                machine=machine,
                state=state,
                parameters=item,
                observation=observation,
                record=record,
                trade_date=trade_date,
                trading_index=trading_index,
                is_evaluation=is_evaluation,
                windows=ordered_windows,
                market_trading_dates=ordered_market_dates,
                config=config,
                panel_snapshot_id=panel_snapshot_id,
                signals=signals,
                trades=trades,
            )
        if observation.tradable:
            trading_index += 1
        previous_close = _optional_float(record.get("close"))

    open_exposures = tuple(
        exposure
        for parameters_item, state in zip(selected, states, strict=True)
        if (exposure := _open_exposure(parameters_item, state)) is not None
    )
    return ExactReplayResult(
        parameters=selected,
        input_rows=input_rows,
        evaluation_rows=evaluation_rows,
        panel_passes=1,
        signals=tuple(signals),
        trades=tuple(trades),
        open_exposures=open_exposures,
    )


def evaluate_exact_entry_lattice_symbol_vectorized(
    records: Iterable[Mapping[str, object]],
    windows: Sequence[ExecutionWindow],
    market_trading_dates: Sequence[date],
    config: MarkupRetestConfig,
    parameters: Sequence[StrategyParameters],
    *,
    panel_snapshot_id: str = "panel-in-memory",
    anchor_retention_resolver: AnchorRetentionResolver | None = None,
) -> ExactReplayResult:
    """Replay a fixed-exit entry grid with exact execution and shared state math.

    The canonical signal constructor and exact entry/exit simulators remain the
    source of truth. Only the 81 independent lifecycle memories are represented
    as arrays, so threshold comparisons and identical lineage lookups happen
    once per observation instead of once per scalar machine.
    """

    selected = tuple(parameters)
    _validate_parameters(selected)
    _validate_fixed_exit_grid(selected)
    size = len(selected)
    setup_threshold = np.asarray(
        [item.setup_score_min for item in selected], dtype=np.float64
    )
    breakout_threshold = np.asarray(
        [item.breakout_buffer_atr for item in selected], dtype=np.float64
    )
    retest_depth_threshold = np.asarray(
        [item.max_retest_depth_atr for item in selected], dtype=np.float64
    )
    migration_threshold = np.asarray(
        [item.min_cost_migration_atr for item in selected], dtype=np.float64
    )
    machines = tuple(
        LifecycleMachine(
            config,
            item,
            anchor_retention_resolver=anchor_retention_resolver,
        )
        for item in selected
    )

    state = np.full(size, _NEUTRAL, dtype=np.uint8)
    cooldown = np.zeros(size, dtype=np.int16)
    breakout_index = np.full(size, -1, dtype=np.int32)
    holding_days = np.zeros(size, dtype=np.int16)
    distribution_days = np.zeros(size, dtype=np.int8)
    active = np.zeros(size, dtype=np.bool_)
    accumulation_at = _empty_objects(size)
    accumulation_index = np.full(size, -1, dtype=np.int32)
    breakout_at = _empty_objects(size)
    active_signal_id = _empty_objects(size)
    anchors = _empty_anchors(size)
    root_anchors = _empty_objects(size)
    comparison_anchors = _empty_objects(size)
    working_anchors = _empty_objects(size)
    anchor_chains = _empty_objects(size)
    positions: list[_Position | None] = [None] * size
    pending_entries: list[_PendingEntry | None] = [None] * size
    pending_exits: list[_PendingExit | None] = [None] * size

    raw_records = [dict(record) for record in records]
    first_broken_date = _first_action_coordinate_mismatch(raw_records)
    ordered_windows = tuple(
        sorted(windows, key=lambda item: (item.trade_date, item.window_index, item.available_at))
    )
    if first_broken_date is not None:
        ordered_windows = tuple(
            replace(window, corporate_action_blocking=True)
            if window.trade_date >= first_broken_date
            else window
            for window in ordered_windows
        )
    ordered_market_dates = tuple(sorted(dict.fromkeys(market_trading_dates)))
    signals: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    signal_counts: Counter[str] = Counter()
    evaluation_counts: Counter[str] = Counter()
    annual_counts: dict[str, Counter[int]] = {
        item.parameter_id: Counter() for item in selected
    }
    input_rows = 0
    evaluation_rows = 0
    trading_index = 0
    symbol: str | None = None
    previous_date: date | None = None
    previous_close: float | None = None
    action_coordinate_broken = False

    for raw_record in raw_records:
        record = dict(raw_record)
        mismatch = _action_coordinate_mismatch(record, previous_close)
        action_coordinate_broken = action_coordinate_broken or mismatch
        if action_coordinate_broken:
            reasons = [
                item
                for item in str(record.get("reason_codes") or "").split("|")
                if item
            ]
            reasons.append("ACTION_PRICE_COORDINATE_MISMATCH")
            record.update(
                {
                    "research_hard_valid": False,
                    "corporate_action_blocking": bool(
                        record.get("corporate_action_blocking")
                    )
                    or mismatch,
                    "share_multiplier": 1.0,
                    "cash_per_share": 0.0,
                    "reason_codes": "|".join(dict.fromkeys(reasons)),
                }
            )
        observation = observation_from_record(record, config, panel_snapshot_id)
        trade_date = _as_date(record.get("trade_date"), field="trade_date")
        if symbol is None:
            symbol = observation.symbol
        elif observation.symbol != symbol:
            raise ValueError(
                "vectorized exact symbol replay received multiple symbols: "
                f"{symbol}, {observation.symbol}"
            )
        if previous_date is not None and trade_date <= previous_date:
            raise ValueError(
                "vectorized exact replay requires unique ordered dates: "
                f"previous={previous_date}, current={trade_date}"
            )
        previous_date = trade_date
        is_evaluation = bool(record.get("is_evaluation_row"))
        input_rows += 1
        evaluation_rows += int(is_evaluation)

        _rebase_lattice_for_action(
            observation,
            anchors=anchors,
            comparison_anchors=comparison_anchors,
        )
        for position in positions:
            if position is not None:
                _apply_position_action(position, observation, trade_date)

        remaining = np.ones(size, dtype=np.bool_)
        for index, pending_entry in enumerate(pending_entries):
            if pending_entry is None:
                continue
            entry_execution = pending_entry.execution
            if entry_execution.status == EntryExecutionStatus.FILLED:
                fill_date = _required_datetime(
                    entry_execution.fill_at, "entry fill_at"
                ).date()
                if trade_date < fill_date:
                    remaining[index] = False
                    continue
                if trade_date > fill_date:
                    raise RuntimeError(
                        f"daily panel is missing entry fill date {fill_date} "
                        f"for {pending_entry.signal.symbol}"
                    )
                positions[index] = _Position(
                    signal=pending_entry.signal,
                    entry=entry_execution,
                    is_evaluation=pending_entry.is_evaluation,
                    quantity=entry_execution.quantity,
                )
                pending_entries[index] = None
                continue
            if entry_execution.status == EntryExecutionStatus.FAILED:
                terminal_date = _terminal_attempt_date(entry_execution)
                if trade_date < terminal_date:
                    remaining[index] = False
                    continue
                if trade_date > terminal_date:
                    raise RuntimeError(
                        f"daily panel is missing entry failure date {terminal_date} "
                        f"for {pending_entry.signal.symbol}"
                    )
                _reset_vector_index(
                    index,
                    cooldown_days=config.windows.cooldown,
                    state=state,
                    cooldown=cooldown,
                    holding_days=holding_days,
                    distribution_days=distribution_days,
                    active=active,
                    accumulation_at=accumulation_at,
                    accumulation_index=accumulation_index,
                    breakout_at=breakout_at,
                    breakout_index=breakout_index,
                    anchors=anchors,
                    root_anchors=root_anchors,
                    comparison_anchors=comparison_anchors,
                    working_anchors=working_anchors,
                    anchor_chains=anchor_chains,
                    active_signal_id=active_signal_id,
                )
                pending_entries[index] = None
                remaining[index] = False
                continue
            if entry_execution.status == EntryExecutionStatus.PENDING:
                remaining[index] = False
                continue
            raise RuntimeError(
                f"unexpected pending entry status: {entry_execution.status}"
            )

        for index, pending_exit in enumerate(pending_exits):
            if pending_exit is None or not remaining[index]:
                continue
            exit_execution = pending_exit.execution
            if exit_execution.status == ExitExecutionStatus.FILLED:
                fill_date = _required_datetime(
                    exit_execution.fill_at, "exit fill_at"
                ).date()
                if trade_date < fill_date:
                    remaining[index] = False
                    continue
                if trade_date > fill_date:
                    raise RuntimeError(
                        f"daily panel is missing exit fill date {fill_date} "
                        f"for {pending_exit.intent.symbol}"
                    )
                position = positions[index]
                if position is None:
                    raise RuntimeError("vectorized exact exit has no filled position")
                adjusted_intent = replace(
                    pending_exit.intent, quantity=position.quantity
                )
                exact_fill = execute_exit(
                    adjusted_intent,
                    ordered_windows,
                    market_trading_dates=ordered_market_dates,
                    settings=config.execution,
                )
                if (
                    exact_fill.status != ExitExecutionStatus.FILLED
                    or exact_fill.fill_at != exit_execution.fill_at
                ):
                    raise RuntimeError(
                        "corporate-action quantity reconciliation changed exit timing"
                    )
                trades.append(
                    _trade_record(selected[index], position, adjusted_intent, exact_fill)
                )
                positions[index] = None
                pending_exits[index] = None
                _reset_vector_index(
                    index,
                    cooldown_days=config.windows.cooldown,
                    state=state,
                    cooldown=cooldown,
                    holding_days=holding_days,
                    distribution_days=distribution_days,
                    active=active,
                    accumulation_at=accumulation_at,
                    accumulation_index=accumulation_index,
                    breakout_at=breakout_at,
                    breakout_index=breakout_index,
                    anchors=anchors,
                    root_anchors=root_anchors,
                    comparison_anchors=comparison_anchors,
                    working_anchors=working_anchors,
                    anchor_chains=anchor_chains,
                    active_signal_id=active_signal_id,
                )
                remaining[index] = False
                continue
            if exit_execution.status in {
                ExitExecutionStatus.PENDING,
                ExitExecutionStatus.BLOCKED_INTENT,
            }:
                remaining[index] = False
                continue
            raise RuntimeError(
                f"unexpected pending exit status: {exit_execution.status}"
            )

        invalid = observation.corporate_action_blocking or not observation.hard_valid
        if invalid:
            for index in np.flatnonzero(remaining & active):
                position = positions[index]
                if position is None:
                    raise RuntimeError("active exact lifecycle has no filled position")
                invalid_reason = (
                    ExitReason.CORPORATE_ACTION
                    if observation.corporate_action_blocking
                    else ExitReason.DATA_INVALID
                )
                pending_exits[index] = _vector_exit(
                    reason=invalid_reason,
                    position=position,
                    observation=observation,
                    parameters=selected[index],
                    windows=ordered_windows,
                    market_trading_dates=ordered_market_dates,
                    config=config,
                )
                remaining[index] = False
            invalid_flat = remaining & ~active
            if np.any(invalid_flat):
                state[invalid_flat] = _BROKEN
                holding_days[invalid_flat] = 0
                distribution_days[invalid_flat] = 0
                active_signal_id[invalid_flat] = None
                _clear_anchor_state(
                    invalid_flat,
                    accumulation_at=accumulation_at,
                    accumulation_index=accumulation_index,
                    breakout_at=breakout_at,
                    breakout_index=breakout_index,
                    anchors=anchors,
                    root_anchors=root_anchors,
                    comparison_anchors=comparison_anchors,
                    working_anchors=working_anchors,
                    anchor_chains=anchor_chains,
                )
                remaining[invalid_flat] = False

        if observation.tradable:
            open_mask = remaining & active
            lineage_cache: dict[
                tuple[str, float, float, float, int], tuple[bool, bool, float]
            ] = {}
            for index in np.flatnonzero(open_mask):
                position = positions[index]
                if position is None:
                    raise RuntimeError("active exact lifecycle has no filled position")
                root = _lifecycle_anchor(root_anchors[index], index=index)
                comparison = _lifecycle_anchor(
                    comparison_anchors[index], index=index
                )
                cache_key = (
                    root.anchor_id,
                    comparison.lower,
                    comparison.upper,
                    comparison.band_width,
                    comparison.peak_count,
                )
                cached = lineage_cache.get(cache_key)
                if cached is None:
                    estimate = exact_anchor_retention(
                        root,
                        observation,
                        resolver=anchor_retention_resolver,
                    )
                    cached = (
                        estimate is not None,
                        (
                            chip_structure_broken(
                                root,
                                observation,
                                config.fixed,
                                comparison_anchor=comparison,
                                resolver=anchor_retention_resolver,
                            )
                            if estimate is not None
                            else False
                        ),
                        (
                            distribution_score_with_anchor(
                                root,
                                observation,
                                config.fixed,
                                resolver=anchor_retention_resolver,
                            )
                            if estimate is not None
                            else float("-inf")
                        ),
                    )
                    lineage_cache[cache_key] = cached
                has_lineage, structure_broken, distribution_score = cached
                open_reason: ExitReason | None = None
                if not has_lineage:
                    open_reason = ExitReason.DATA_INVALID
                else:
                    holding_days[index] += 1
                    if structure_broken:
                        open_reason = ExitReason.STRUCTURE_BROKEN
                    elif observation.close < (
                        anchors["support"][index]
                        - selected[index].protective_stop_atr * observation.atr
                    ):
                        open_reason = ExitReason.PROTECTIVE_STOP
                    elif holding_days[index] >= config.windows.max_holding:
                        open_reason = ExitReason.MAX_HOLDING_PERIOD
                    else:
                        distributing = (
                            distribution_score
                            >= selected[index].distribution_score_min
                        )
                        distribution_days[index] = (
                            distribution_days[index] + 1 if distributing else 0
                        )
                        state[index] = _ACTIVE
                        if (
                            distribution_days[index]
                            >= config.windows.exit_confirmation
                        ):
                            open_reason = ExitReason.DISTRIBUTION_CONFIRMED
                if open_reason is not None:
                    pending_exits[index] = _vector_exit(
                        reason=open_reason,
                        position=position,
                        observation=observation,
                        parameters=selected[index],
                        windows=ordered_windows,
                        market_trading_dates=ordered_market_dates,
                        config=config,
                    )
                remaining[index] = False

            eligible = remaining & ~active
            cooling = eligible & (cooldown > 0)
            cooldown[cooling] -= 1
            eligible &= ~cooling
            if np.any(eligible):

                def capture_signal(
                    index: int,
                    signal: StrategySignal,
                    observation: LifecycleObservation = observation,
                    record: Mapping[str, object] = record,
                    is_evaluation: bool = is_evaluation,
                ) -> None:
                    execution = execute_entry(
                        signal,
                        ordered_windows,
                        market_trading_dates=ordered_market_dates,
                        settings=config.execution,
                        scope=ExecutionScope.RESEARCH_EVENT_STUDY,
                    )
                    signals.append(
                        _signal_record(
                            signal,
                            execution,
                            observation,
                            record,
                            panel_snapshot_id=panel_snapshot_id,
                            is_evaluation=is_evaluation,
                        )
                    )
                    if execution.status == EntryExecutionStatus.BLOCKED_SIGNAL:
                        _reset_vector_index(
                            index,
                            cooldown_days=config.windows.cooldown,
                            state=state,
                            cooldown=cooldown,
                            holding_days=holding_days,
                            distribution_days=distribution_days,
                            active=active,
                            accumulation_at=accumulation_at,
                            accumulation_index=accumulation_index,
                            breakout_at=breakout_at,
                            breakout_index=breakout_index,
                            anchors=anchors,
                            root_anchors=root_anchors,
                            comparison_anchors=comparison_anchors,
                            working_anchors=working_anchors,
                            anchor_chains=anchor_chains,
                            active_signal_id=active_signal_id,
                        )
                        return
                    pending_entries[index] = _PendingEntry(
                        signal=signal,
                        execution=execution,
                        is_evaluation=is_evaluation,
                    )

                _advance_entries(
                    eligible=eligible,
                    state=state,
                    setup=observation.setup_score >= setup_threshold,
                    breakout=observation.breakout_excess_atr
                    >= breakout_threshold,
                    retest_depth_threshold=retest_depth_threshold,
                    migration_threshold=migration_threshold,
                    observation=observation,
                    trading_index=trading_index,
                    config=config,
                    cooldown=cooldown,
                    accumulation_at=accumulation_at,
                    accumulation_index=accumulation_index,
                    breakout_at=breakout_at,
                    breakout_index=breakout_index,
                    anchors=anchors,
                    root_anchors=root_anchors,
                    comparison_anchors=comparison_anchors,
                    working_anchors=working_anchors,
                    anchor_chains=anchor_chains,
                    active=active,
                    active_signal_id=active_signal_id,
                    machines=machines,
                    parameters=selected,
                    signals=None,
                    signal_sink=None,
                    lifecycle_signal_sink=capture_signal,
                    signal_counts=signal_counts,
                    evaluation_counts=evaluation_counts,
                    annual_counts=annual_counts,
                    panel_snapshot_id=panel_snapshot_id,
                    is_evaluation=is_evaluation,
                    anchor_retention_resolver=anchor_retention_resolver,
                )
            trading_index += 1
        previous_close = _optional_float(record.get("close"))

    open_exposures = tuple(
        exposure
        for index, parameters_item in enumerate(selected)
        if (
            exposure := _open_exposure(
                parameters_item,
                _ParameterState(
                    position=positions[index],
                    pending_entry=pending_entries[index],
                    pending_exit=pending_exits[index],
                ),
            )
        )
        is not None
    )
    return ExactReplayResult(
        parameters=selected,
        input_rows=input_rows,
        evaluation_rows=evaluation_rows,
        panel_passes=1,
        signals=tuple(signals),
        trades=tuple(trades),
        open_exposures=open_exposures,
    )


def _validate_fixed_exit_grid(parameters: Sequence[StrategyParameters]) -> None:
    exits = {
        (item.distribution_score_min, item.protective_stop_atr)
        for item in parameters
    }
    if len(exits) != 1:
        raise ValueError(
            "vectorized exact entry replay requires one controlled exit setting"
        )


def _apply_position_action(
    position: _Position,
    observation: LifecycleObservation,
    trade_date: date,
) -> None:
    entry_date = _required_datetime(position.entry.fill_at, "entry fill_at").date()
    if trade_date <= entry_date:
        return
    multiplier = observation.share_multiplier
    cash = observation.cash_per_share
    if multiplier == 1.0 and cash == 0.0:
        return
    position.dividends += position.quantity * cash
    position.quantity = round(position.quantity * multiplier)
    position.action_snapshots.extend(observation.snapshot_ids)


def _vector_exit(
    *,
    reason: ExitReason,
    position: _Position,
    observation: LifecycleObservation,
    parameters: StrategyParameters,
    windows: Sequence[ExecutionWindow],
    market_trading_dates: Sequence[date],
    config: MarkupRetestConfig,
) -> _PendingExit:
    intent = _exit_intent(reason, position, observation, parameters)
    execution = execute_exit(
        intent,
        windows,
        market_trading_dates=market_trading_dates,
        settings=config.execution,
    )
    return _PendingExit(intent=intent, execution=execution)


def _reset_vector_index(
    index: int,
    *,
    cooldown_days: int,
    state: np.ndarray[Any, Any],
    cooldown: np.ndarray[Any, Any],
    holding_days: np.ndarray[Any, Any],
    distribution_days: np.ndarray[Any, Any],
    active: np.ndarray[Any, Any],
    accumulation_at: np.ndarray[Any, Any],
    accumulation_index: np.ndarray[Any, Any],
    breakout_at: np.ndarray[Any, Any],
    breakout_index: np.ndarray[Any, Any],
    anchors: Mapping[str, np.ndarray[Any, Any]],
    root_anchors: np.ndarray[Any, Any],
    comparison_anchors: np.ndarray[Any, Any],
    working_anchors: np.ndarray[Any, Any],
    anchor_chains: np.ndarray[Any, Any],
    active_signal_id: np.ndarray[Any, Any],
) -> None:
    mask = np.zeros(len(state), dtype=np.bool_)
    mask[index] = True
    state[index] = _NEUTRAL
    cooldown[index] = cooldown_days
    holding_days[index] = 0
    distribution_days[index] = 0
    active[index] = False
    active_signal_id[index] = None
    _clear_anchor_state(
        mask,
        accumulation_at=accumulation_at,
        accumulation_index=accumulation_index,
        breakout_at=breakout_at,
        breakout_index=breakout_index,
        anchors=anchors,
        root_anchors=root_anchors,
        comparison_anchors=comparison_anchors,
        working_anchors=working_anchors,
        anchor_chains=anchor_chains,
    )


def evaluate_exact_parameter_lattice_files(
    files: Sequence[Path],
    config: MarkupRetestConfig,
    stage: StrategyStage | str,
    parameters: Sequence[StrategyParameters],
    *,
    panel_snapshot_id: str,
    threads: int | None = None,
    symbols: Sequence[str] | None = None,
    vectorized_entry_grid: bool = False,
    coalesce_buckets: bool = False,
) -> ExactReplayResult:
    """Replay a partitioned panel once with up to ten independent workers."""

    selected = tuple(parameters)
    _validate_parameters(selected)
    boundary = config.stage(stage)
    if boundary.name == StrategyStage.RESEALED:
        frozen = load_passing_frozen_parameters(config)
        if selected != (frozen,):
            raise ValueError(
                "resealed exact replay requires exactly the frozen economic parameter"
            )
    panel_groups = _group_panel_files(files)
    if not panel_groups:
        raise ValueError("exact parameter replay requires panel parquet files")
    execution_files = tuple(
        config.assets.execution_file(year) for year in boundary.years()
    )
    config.assert_input_files(stage, execution_files)
    missing = [str(path) for path in execution_files if not path.is_file()]
    if missing:
        raise FileNotFoundError("missing registered execution input: " + ", ".join(missing))
    market_dates = _market_trading_dates(
        execution_files,
        start=boundary.history_start,
        end=boundary.max_input_date,
    )
    requested = threads if threads is not None else (os.cpu_count() or 1)
    symbols_by_bucket = _symbols_by_bucket(symbols)
    if symbols_by_bucket is not None:
        panel_groups = tuple(
            group for group in panel_groups if group[0] in symbols_by_bucket
        )
        if not panel_groups:
            raise ValueError("none of the requested repair symbols have panel buckets")
    worker_count = min(max(requested, 1), 10, len(panel_groups))
    worker_groups = (
        _coalesce_panel_groups(panel_groups, worker_count)
        if coalesce_buckets
        else tuple(((bucket,), paths) for bucket, paths in panel_groups)
    )
    arguments = tuple(
        (
            paths,
            buckets,
            execution_files,
            market_dates,
            config,
            selected,
            panel_snapshot_id,
            vectorized_entry_grid,
            (
                tuple(
                    symbol
                    for bucket in buckets
                    for symbol in symbols_by_bucket[bucket]
                )
                if symbols_by_bucket is not None
                else None
            ),
        )
        for buckets, paths in worker_groups
    )
    worker_count = min(worker_count, len(arguments))
    if worker_count == 1:
        results = tuple(_evaluate_partition(item) for item in arguments)
    else:
        with ProcessPoolExecutor(max_workers=worker_count) as executor:
            results = tuple(executor.map(_evaluate_partition, arguments))
    return _merge_results(results)


def _advance_parameter(
    *,
    machine: LifecycleMachine,
    state: _ParameterState,
    parameters: StrategyParameters,
    observation: LifecycleObservation,
    record: Mapping[str, object],
    trade_date: date,
    trading_index: int,
    is_evaluation: bool,
    windows: Sequence[ExecutionWindow],
    market_trading_dates: Sequence[date],
    config: MarkupRetestConfig,
    panel_snapshot_id: str,
    signals: list[dict[str, Any]],
    trades: list[dict[str, Any]],
) -> None:
    observation_valid = (
        observation.hard_valid
        and not observation.corporate_action_blocking
        and observation.peak_identity_valid
    )
    if observation_valid:
        _apply_corporate_action(state, observation, trade_date)

    if state.pending_entry is not None:
        if _advance_pending_entry(
            state,
            machine,
            observation,
            trade_date,
        ):
            return

    if state.pending_exit is not None:
        if _advance_pending_exit(
            state=state,
            machine=machine,
            parameters=parameters,
            observation=observation,
            trade_date=trade_date,
            windows=windows,
            market_trading_dates=market_trading_dates,
            config=config,
            trades=trades,
        ):
            return

    transition = machine.advance(
        state.memory,
        observation,
        trading_index=trading_index,
    )
    state.memory = transition.memory
    if transition.signal is not None:
        execution = execute_entry(
            transition.signal,
            windows,
            market_trading_dates=market_trading_dates,
            settings=config.execution,
            scope=ExecutionScope.RESEARCH_EVENT_STUDY,
        )
        state.pending_entry = _PendingEntry(
            signal=transition.signal,
            execution=execution,
            is_evaluation=is_evaluation,
        )
        signals.append(
            _signal_record(
                transition.signal,
                execution,
                observation,
                record,
                panel_snapshot_id=panel_snapshot_id,
                is_evaluation=is_evaluation,
            )
        )
        if execution.status == EntryExecutionStatus.BLOCKED_SIGNAL:
            state.memory = machine.after_exit()
            state.pending_entry = None
        return

    if transition.exit_reason is not None:
        if state.position is None:
            raise RuntimeError("exact exit intent has no filled position")
        intent = _exit_intent(
            transition.exit_reason,
            state.position,
            observation,
            parameters,
        )
        exit_execution = execute_exit(
            intent,
            windows,
            market_trading_dates=market_trading_dates,
            settings=config.execution,
        )
        state.pending_exit = _PendingExit(
            intent=intent,
            execution=exit_execution,
        )


def _advance_pending_entry(
    state: _ParameterState,
    machine: LifecycleMachine,
    observation: LifecycleObservation,
    trade_date: date,
) -> bool:
    pending = cast(_PendingEntry, state.pending_entry)
    if (
        not observation.hard_valid
        or observation.corporate_action_blocking
        or not observation.peak_identity_valid
    ):
        state.memory = machine.advance(
            state.memory, observation, trading_index=0
        ).memory
        state.pending_entry = None
        return True
    execution = pending.execution
    if execution.status == EntryExecutionStatus.FILLED:
        fill_date = _required_datetime(execution.fill_at, "entry fill_at").date()
        if trade_date < fill_date:
            state.memory = rebase_lifecycle_memory(state.memory, observation)
            return True
        if trade_date > fill_date:
            raise RuntimeError(
                f"daily panel is missing entry fill date {fill_date} for {pending.signal.symbol}"
            )
        state.position = _Position(
            signal=pending.signal,
            entry=execution,
            is_evaluation=pending.is_evaluation,
            quantity=execution.quantity,
        )
        state.pending_entry = None
        return False

    if execution.status == EntryExecutionStatus.FAILED:
        terminal_date = _terminal_attempt_date(execution)
        if trade_date < terminal_date:
            state.memory = rebase_lifecycle_memory(state.memory, observation)
            return True
        if trade_date > terminal_date:
            raise RuntimeError(
                f"daily panel is missing entry failure date {terminal_date} "
                f"for {pending.signal.symbol}"
            )
        state.memory = machine.after_exit()
        state.pending_entry = None
        return True

    if execution.status == EntryExecutionStatus.PENDING:
        state.memory = rebase_lifecycle_memory(state.memory, observation)
        return True
    raise RuntimeError(f"unexpected pending entry status: {execution.status}")


def _advance_pending_exit(
    *,
    state: _ParameterState,
    machine: LifecycleMachine,
    parameters: StrategyParameters,
    observation: LifecycleObservation,
    trade_date: date,
    windows: Sequence[ExecutionWindow],
    market_trading_dates: Sequence[date],
    config: MarkupRetestConfig,
    trades: list[dict[str, Any]],
) -> bool:
    pending = cast(_PendingExit, state.pending_exit)
    if pending.execution.status == ExitExecutionStatus.FILLED:
        fill_date = _required_datetime(pending.execution.fill_at, "exit fill_at").date()
        if trade_date < fill_date:
            state.memory = machine.advance(
                state.memory, observation, trading_index=0
            ).memory
            return True
        if trade_date > fill_date:
            raise RuntimeError(
                f"daily panel is missing exit fill date {fill_date} for {pending.intent.symbol}"
            )
        position = cast(_Position, state.position)
        adjusted_intent = replace(pending.intent, quantity=position.quantity)
        exact_fill = execute_exit(
            adjusted_intent,
            windows,
            market_trading_dates=market_trading_dates,
            settings=config.execution,
        )
        if (
            exact_fill.status != ExitExecutionStatus.FILLED
            or exact_fill.fill_at != pending.execution.fill_at
        ):
            raise RuntimeError("corporate-action quantity reconciliation changed exit timing")
        trades.append(_trade_record(parameters, position, adjusted_intent, exact_fill))
        state.memory = machine.after_exit()
        state.position = None
        state.pending_exit = None
        return True

    if pending.execution.status in {
        ExitExecutionStatus.PENDING,
        ExitExecutionStatus.BLOCKED_INTENT,
    }:
        state.memory = machine.advance(
            state.memory, observation, trading_index=0
        ).memory
        return True
    raise RuntimeError(f"unexpected pending exit status: {pending.execution.status}")


def _apply_corporate_action(
    state: _ParameterState,
    observation: LifecycleObservation,
    trade_date: date,
) -> None:
    position = state.position
    if position is None:
        return
    entry_date = _required_datetime(position.entry.fill_at, "entry fill_at").date()
    if trade_date <= entry_date:
        return
    multiplier = observation.share_multiplier
    cash = observation.cash_per_share
    if multiplier == 1.0 and cash == 0.0:
        return
    position.dividends += position.quantity * cash
    position.quantity = round(position.quantity * multiplier)
    position.action_snapshots.extend(observation.snapshot_ids)


def _exit_intent(
    reason: ExitReason,
    position: _Position,
    observation: LifecycleObservation,
    parameters: StrategyParameters,
) -> ExitIntent:
    identity = "|".join(
        (
            "EXIT",
            position.signal.signal_id,
            observation.decision_at.isoformat(),
            reason.value,
            parameters.parameter_id,
        )
    )
    return ExitIntent(
        intent_id=_sha256_text(identity),
        signal_id=position.signal.signal_id,
        symbol=position.signal.symbol,
        decision_at=observation.decision_at,
        reason=reason,
        quantity=position.quantity,
        reference_price=observation.close,
        available_at=observation.available_at,
        snapshot_ids=observation.snapshot_ids,
        hard_valid=observation.hard_valid,
    )


def _signal_record(
    signal: StrategySignal,
    execution: EntryExecution,
    observation: LifecycleObservation,
    record: Mapping[str, object],
    *,
    panel_snapshot_id: str,
    is_evaluation: bool,
) -> dict[str, Any]:
    payload = serialize_signal(
        signal,
        panel_snapshot_id=panel_snapshot_id,
        is_evaluation=is_evaluation,
    )
    payload.update(
        {
            "entry_status": execution.status.value,
            "entry_fill_at": execution.fill_at.isoformat() if execution.fill_at else None,
            "entry_fill_price": execution.fill_price,
            "entry_quantity": execution.quantity,
            "entry_total_cash": execution.total_cash,
            "entry_reason_codes": list(execution.reason_codes),
            "setup_score": observation.setup_score,
            "breakout_excess_atr": observation.breakout_excess_atr,
            "close_to_p90_atr": (
                (observation.close - observation.cost_p90) / observation.atr
            ),
            "chip_model_disagreement_atr": observation.chip_model_disagreement_atr,
            "momentum_20": _optional_float(record.get("momentum_20")),
        }
    )
    return payload


def _trade_record(
    parameters: StrategyParameters,
    position: _Position,
    intent: ExitIntent,
    execution: ExitExecution,
) -> dict[str, Any]:
    if execution.fill_at is None or execution.fill_price is None:
        raise ValueError("trade record requires a filled exit")
    net_pnl = execution.net_proceeds + position.dividends - position.entry.total_cash
    return {
        "parameter_id": parameters.parameter_id,
        "parameters": parameters.canonical(),
        "signal_id": position.signal.signal_id,
        "symbol": position.signal.symbol,
        "signal_at": position.signal.decision_at.isoformat(),
        "entry_at": _required_datetime(position.entry.fill_at, "entry fill_at").isoformat(),
        "entry_price": position.entry.fill_price,
        "entry_cash": position.entry.total_cash,
        "entry_quantity": position.entry.quantity,
        "exit_intent_at": intent.decision_at.isoformat(),
        "exit_at": execution.fill_at.isoformat(),
        "exit_price": execution.fill_price,
        "exit_reason": intent.reason.value,
        "exit_quantity": execution.quantity,
        "dividends": position.dividends,
        "net_pnl": net_pnl,
        "return_fraction": net_pnl / position.entry.total_cash,
        "blocked_tail_loss": execution.blocked_tail_loss,
        "is_evaluation_row": position.is_evaluation,
        "entry_snapshot_ids": list(position.entry.snapshot_ids),
        "exit_snapshot_ids": list(execution.snapshot_ids),
        "corporate_action_snapshot_ids": list(dict.fromkeys(position.action_snapshots)),
    }


def _open_exposure(
    parameters: StrategyParameters,
    state: _ParameterState,
) -> dict[str, Any] | None:
    signal: StrategySignal | None = None
    status: str | None = None
    reason_codes: tuple[str, ...] = ()
    if state.pending_entry is not None:
        signal = state.pending_entry.signal
        status = f"ENTRY_{state.pending_entry.execution.status.value}"
        reason_codes = state.pending_entry.execution.reason_codes
    elif state.position is not None:
        signal = state.position.signal
        if state.pending_exit is not None:
            status = f"EXIT_{state.pending_exit.execution.status.value}"
            reason_codes = state.pending_exit.execution.reason_codes
        else:
            status = "POSITION_OPEN"
    if signal is None or status is None:
        return None
    return {
        "parameter_id": parameters.parameter_id,
        "signal_id": signal.signal_id,
        "symbol": signal.symbol,
        "signal_at": signal.decision_at.isoformat(),
        "status": status,
        "reason_codes": list(reason_codes),
        "is_evaluation_row": (
            state.pending_entry.is_evaluation
            if state.pending_entry is not None
            else cast(_Position, state.position).is_evaluation
        ),
    }


def _evaluate_partition(
    arguments: tuple[
        tuple[Path, ...],
        tuple[int, ...],
        tuple[Path, ...],
        tuple[date, ...],
        MarkupRetestConfig,
        tuple[StrategyParameters, ...],
        str,
        bool,
        tuple[str, ...] | None,
    ],
) -> ExactReplayResult:
    (
        panel_files,
        buckets,
        execution_files,
        market_dates,
        config,
        parameters,
        panel_snapshot_id,
        vectorized_entry_grid,
        symbols,
    ) = arguments
    resolver = (
        StreamingLineageSession(config.assets.chip_lineage_root)
        if config.assets.chip_lineage_root is not None
        else None
    )
    panel_groups = itertools.groupby(
        stream_panel(panel_files, symbols=symbols), key=lambda row: str(row["symbol"])
    )
    execution_groups = iter(
        itertools.groupby(
            _stream_execution_windows(execution_files, buckets, symbols=symbols),
            key=lambda window: window.symbol,
        )
    )
    current_execution = next(execution_groups, None)
    results: list[ExactReplayResult] = []
    for symbol, symbol_records in panel_groups:
        while current_execution is not None and current_execution[0] < symbol:
            current_execution = next(execution_groups, None)
        if current_execution is not None and current_execution[0] == symbol:
            symbol_windows = tuple(current_execution[1])
            current_execution = next(execution_groups, None)
        else:
            symbol_windows = ()
        replay = (
            evaluate_exact_entry_lattice_symbol_vectorized
            if vectorized_entry_grid
            else evaluate_exact_parameter_lattice_symbol
        )
        result = replay(
            symbol_records,
            symbol_windows,
            market_dates,
            config,
            parameters,
            panel_snapshot_id=panel_snapshot_id,
            anchor_retention_resolver=resolver,
        )
        results.append(result)
        if resolver is not None:
            resolver.release_symbol(symbol)
    return _merge_results(results)


def _stream_execution_windows(
    files: Sequence[Path],
    buckets: Sequence[int],
    *,
    symbols: Sequence[str] | None = None,
) -> Iterator[ExecutionWindow]:
    sql_files = "[" + ",".join(_sql_text(str(path)) for path in files) + "]"
    bucket_sql = ",".join(str(int(bucket)) for bucket in buckets)
    symbol_filter = ""
    if symbols is not None:
        if not symbols:
            return
        symbol_sql = ",".join(_sql_text(symbol) for symbol in symbols)
        symbol_filter = f"AND symbol IN ({symbol_sql})"
    con = duckdb.connect()
    try:
        con.execute("SET threads = 1")
        query = con.execute(
            f"""
            SELECT
                symbol, trade_date, window_index, available_at,
                open, high, low, close, volume, amount, trade_status,
                up_limit_price, down_limit_price, market_rule_valid,
                hard_valid, invalid_reasons, snapshot_id, daily_snapshot_id
            FROM read_parquet({sql_files}, union_by_name=true)
            WHERE abs(hash(symbol) % 32) IN ({bucket_sql})
              {symbol_filter}
            ORDER BY symbol, trade_date, window_index, available_at
            """
        )
        reader = query.fetch_record_batch(65_536)
        for batch in reader:
            names = batch.schema.names
            columns = [batch.column(index).to_pylist() for index in range(len(names))]
            for values in zip(*columns, strict=True):
                row = dict(zip(names, values, strict=True))
                yield ExecutionWindow(
                    symbol=str(row["symbol"]),
                    trade_date=_as_date(row["trade_date"], field="trade_date"),
                    window_index=int(row["window_index"]),
                    available_at=_aware_datetime(row["available_at"]),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row["volume"]),
                    amount=float(row["amount"]),
                    trade_status=(
                        int(row["trade_status"])
                        if row["trade_status"] is not None
                        else None
                    ),
                    up_limit_price=_optional_float(row["up_limit_price"]),
                    down_limit_price=_optional_float(row["down_limit_price"]),
                    market_rule_valid=bool(row["market_rule_valid"]),
                    hard_valid=bool(row["hard_valid"]),
                    snapshot_id=str(row["snapshot_id"]),
                    daily_snapshot_id=(
                        str(row["daily_snapshot_id"])
                        if row["daily_snapshot_id"] is not None
                        else None
                    ),
                    invalid_reasons=tuple(
                        item
                        for item in str(row.get("invalid_reasons") or "").split("|")
                        if item
                    ),
                )
    finally:
        con.close()


def _market_trading_dates(
    files: Sequence[Path], *, start: date, end: date
) -> tuple[date, ...]:
    sql_files = "[" + ",".join(_sql_text(str(path)) for path in files) + "]"
    con = duckdb.connect()
    try:
        rows = con.execute(
            f"""
            SELECT DISTINCT trade_date
            FROM read_parquet({sql_files}, union_by_name=true)
            WHERE trade_date BETWEEN ? AND ?
            ORDER BY trade_date
            """,
            [start, end],
        ).fetchall()
    finally:
        con.close()
    return tuple(_as_date(row[0], field="trade_date") for row in rows)


def _group_panel_files(
    files: Sequence[Path],
) -> tuple[tuple[int, tuple[Path, ...]], ...]:
    grouped: dict[int, list[Path]] = {}
    for path in files:
        raw = next(
            (
                part.partition("=")[2]
                for part in path.parts
                if part.startswith("symbol_bucket=")
            ),
            None,
        )
        if raw is None or not raw.isdigit():
            raise ValueError(f"panel file has no symbol_bucket partition: {path}")
        grouped.setdefault(int(raw), []).append(path)
    return tuple(
        (bucket, tuple(sorted(grouped[bucket]))) for bucket in sorted(grouped)
    )


def _coalesce_panel_groups(
    groups: Sequence[tuple[int, tuple[Path, ...]]],
    worker_count: int,
) -> tuple[tuple[tuple[int, ...], tuple[Path, ...]], ...]:
    """Assign buckets to long-lived workers so each scans execution files once."""

    count = min(max(worker_count, 1), len(groups))
    bins: list[list[tuple[int, tuple[Path, ...]]]] = [[] for _ in range(count)]
    loads = [0] * count
    weighted = sorted(
        groups,
        key=lambda item: (
            -sum(path.stat().st_size for path in item[1]),
            item[0],
        ),
    )
    for group in weighted:
        target = min(range(count), key=lambda index: (loads[index], index))
        bins[target].append(group)
        loads[target] += sum(path.stat().st_size for path in group[1])
    return tuple(
        (
            tuple(sorted(bucket for bucket, _ in worker_groups)),
            tuple(
                sorted(
                    path
                    for _, paths in worker_groups
                    for path in paths
                )
            ),
        )
        for worker_groups in bins
        if worker_groups
    )


def _symbols_by_bucket(
    symbols: Sequence[str] | None,
) -> dict[int, tuple[str, ...]] | None:
    if symbols is None:
        return None
    selected = tuple(sorted(dict.fromkeys(symbols)))
    if not selected:
        raise ValueError("repair symbol list cannot be empty")
    con = duckdb.connect()
    try:
        rows = con.execute(
            "SELECT unnest AS symbol, abs(hash(unnest) % 32)::INTEGER AS bucket "
            "FROM unnest(?) ORDER BY symbol",
            [list(selected)],
        ).fetchall()
    finally:
        con.close()
    grouped: dict[int, list[str]] = {}
    for symbol, bucket in rows:
        grouped.setdefault(int(bucket), []).append(str(symbol))
    return {bucket: tuple(values) for bucket, values in grouped.items()}


def _merge_results(results: Sequence[ExactReplayResult]) -> ExactReplayResult:
    if not results:
        raise ValueError("cannot merge empty exact replay results")
    parameters = results[0].parameters
    parameter_ids = tuple(item.parameter_id for item in parameters)
    if any(
        tuple(item.parameter_id for item in result.parameters) != parameter_ids
        for result in results[1:]
    ):
        raise ValueError("exact replay workers used different parameter grids")
    return ExactReplayResult(
        parameters=parameters,
        input_rows=sum(result.input_rows for result in results),
        evaluation_rows=sum(result.evaluation_rows for result in results),
        panel_passes=1,
        signals=tuple(
            sorted(
                (row for result in results for row in result.signals),
                key=lambda row: (
                    str(row["parameter_id"]),
                    str(row["symbol"]),
                    str(row["decision_at"]),
                ),
            )
        ),
        trades=tuple(
            sorted(
                (row for result in results for row in result.trades),
                key=lambda row: (
                    str(row["parameter_id"]),
                    str(row["symbol"]),
                    str(row["signal_at"]),
                ),
            )
        ),
        open_exposures=tuple(
            sorted(
                (row for result in results for row in result.open_exposures),
                key=lambda row: (
                    str(row["parameter_id"]),
                    str(row["symbol"]),
                    str(row["signal_at"]),
                ),
            )
        ),
    )


def _validate_parameters(parameters: Sequence[StrategyParameters]) -> None:
    if not parameters:
        raise ValueError("exact replay requires at least one parameter combination")
    ids = tuple(item.parameter_id for item in parameters)
    if len(set(ids)) != len(ids):
        raise ValueError("exact replay parameter combinations must be unique")


def _first_action_coordinate_mismatch(
    records: Sequence[Mapping[str, object]],
) -> date | None:
    previous_close: float | None = None
    for record in records:
        if _action_coordinate_mismatch(record, previous_close):
            return _as_date(record.get("trade_date"), field="trade_date")
        previous_close = _optional_float(record.get("close"))
    return None


def _action_coordinate_mismatch(
    record: Mapping[str, object],
    previous_close: float | None,
) -> bool:
    multiplier = _optional_float(record.get("share_multiplier")) or 1.0
    cash = _optional_float(record.get("cash_per_share")) or 0.0
    if multiplier == 1.0 and cash == 0.0:
        return False
    observed_preclose = _optional_float(record.get("preclose"))
    if previous_close is None or observed_preclose is None:
        return False
    if multiplier <= 0 or previous_close <= cash or observed_preclose <= 0:
        return True
    expected = (previous_close - cash) / multiplier
    tolerance = max(0.02, observed_preclose * 0.001)
    return abs(observed_preclose - expected) > tolerance


def _terminal_attempt_date(execution: EntryExecution) -> date:
    if not execution.attempted_trading_dates:
        raise RuntimeError("failed entry has no attempted trading dates")
    return execution.attempted_trading_dates[-1]


def _required_datetime(value: datetime | None, field: str) -> datetime:
    if value is None:
        raise ValueError(f"{field} is required")
    return value


def _aware_datetime(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"available_at must be datetime, got {type(value).__name__}")
    return value.replace(tzinfo=CN_TZ) if value.tzinfo is None else value


def _as_date(value: object, *, field: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raise TypeError(f"{field} must be date, got {type(value).__name__}")


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    return float(cast(float, value))


def _sql_text(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _sha256_text(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode()).hexdigest()
