"""One-pass parameter-lattice screening for MARKUP_RETEST v1.

The causal panel is expensive and immutable.  This module therefore advances
all 81 entry parameter combinations together while each predictor row is read
exactly once.  Labels are neither accepted nor joined here.  Exit, execution,
matching and calibration are separate downstream gates for the small entry
shortlist.
"""

from __future__ import annotations

import hashlib
import itertools
import os
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from cyq_game.chip.ensemble_v2 import AnchorRetentionEstimate
from cyq_game.domain import ChipLifecycleState
from cyq_game.strategy.chip_lineage import StreamingLineageSession
from cyq_game.strategy.ledger import TrialLedger
from cyq_game.strategy.markup_retest import (
    AnchorRetentionResolver,
    LifecycleAnchor,
    LifecycleMachine,
    LifecycleMemory,
    LifecycleObservation,
    MarkupRetestConfig,
    StrategyParameters,
    StrategySignal,
    assert_no_label_access,
    chip_structure_broken,
    distribution_score_with_anchor,
    exact_anchor_retention,
    freeze_lifecycle_anchor,
    maybe_create_support_anchor,
    rebase_comparison_anchor,
)
from cyq_game.strategy.signals import (
    observation_from_record,
    serialize_signal,
    stream_panel,
)

_NEUTRAL = np.uint8(0)
_ACCUMULATING = np.uint8(1)
_BREAKOUT = np.uint8(2)
_ACTIVE = np.uint8(3)
_BROKEN = np.uint8(4)


@dataclass(frozen=True)
class EntryLatticeResult:
    """Complete, unranked signal output from one predictor-panel pass."""

    parameters: tuple[StrategyParameters, ...]
    signals: tuple[dict[str, Any], ...]
    input_rows: int
    evaluation_rows: int
    panel_passes: int
    signal_counts: Mapping[str, int]
    evaluation_signal_counts: Mapping[str, int]
    annual_evaluation_signal_counts: Mapping[str, Mapping[int, int]]


@dataclass(frozen=True)
class EntryFrequencyTrial:
    """Frequency gate evidence for one of the 81 entry combinations."""

    parameter_id: str
    parameters: StrategyParameters
    annual_signal_counts: Mapping[int, int]
    mean_annual_signals: float
    worst_target_deviation: float
    adjacent_frequency_passes: int
    frequency_gate: str
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class EntryShortlistResult:
    """Deterministic frequency shortlist; never a ranking of stock signals."""

    evaluation_years: tuple[int, ...]
    trials: tuple[EntryFrequencyTrial, ...]
    candidates: tuple[StrategyParameters, ...]
    status: str
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class TrialLedgerWriteResult:
    run_id: str
    appended: int
    existing: int
    ledger_path: Path


SignalSink = Callable[[Mapping[str, Any]], None]
LifecycleSignalSink = Callable[[int, StrategySignal], None]


def entry_parameter_grid(
    config: MarkupRetestConfig,
) -> tuple[StrategyParameters, ...]:
    """Return the configured 3^4 entry grid with fixed default exits."""

    names = (
        "setup_score_min",
        "breakout_buffer_atr",
        "max_retest_depth_atr",
        "min_cost_migration_atr",
    )
    grid = tuple(
        StrategyParameters(
            **dict(zip(names, values, strict=True)),
            distribution_score_min=config.parameters.distribution_score_min,
            protective_stop_atr=config.parameters.protective_stop_atr,
        )
        for values in itertools.product(*(config.parameter_grids[name] for name in names))
    )
    if len(grid) != 81 or len({item.parameter_id for item in grid}) != 81:
        raise ValueError("v1 entry grid must contain exactly 81 unique combinations")
    return grid


def exit_parameter_grid(
    config: MarkupRetestConfig,
    entry: StrategyParameters,
) -> tuple[StrategyParameters, ...]:
    """Return the configured 3^2 exit grid for one shortlisted entry."""

    grid = tuple(
        StrategyParameters(
            setup_score_min=entry.setup_score_min,
            breakout_buffer_atr=entry.breakout_buffer_atr,
            max_retest_depth_atr=entry.max_retest_depth_atr,
            min_cost_migration_atr=entry.min_cost_migration_atr,
            distribution_score_min=distribution,
            protective_stop_atr=stop,
        )
        for distribution, stop in itertools.product(
            config.parameter_grids["distribution_score_min"],
            config.parameter_grids["protective_stop_atr"],
        )
    )
    if len(grid) != 9 or len({item.parameter_id for item in grid}) != 9:
        raise ValueError("v1 exit grid must contain exactly 9 unique combinations")
    return grid


def screen_entry_lattice(
    records: Iterable[Mapping[str, object]],
    config: MarkupRetestConfig,
    *,
    panel_snapshot_id: str = "panel-in-memory",
    signal_sink: SignalSink | None = None,
    collect_signals: bool = True,
    anchor_retention_resolver: AnchorRetentionResolver | None = None,
) -> EntryLatticeResult:
    """Advance the 81-entry lattice while consuming ``records`` once.

    A research-only fill approximation closes a pending exit on the next
    tradable observation and then applies the configured cooldown.  This is
    used only to screen entry combinations.  Shortlisted candidates must pass
    the exact minute execution and exit evaluator before promotion.
    """

    parameters = entry_parameter_grid(config)
    size = len(parameters)
    setup_threshold = np.asarray(
        [item.setup_score_min for item in parameters], dtype=np.float64
    )
    breakout_threshold = np.asarray(
        [item.breakout_buffer_atr for item in parameters], dtype=np.float64
    )
    retest_depth_threshold = np.asarray(
        [item.max_retest_depth_atr for item in parameters], dtype=np.float64
    )
    migration_threshold = np.asarray(
        [item.min_cost_migration_atr for item in parameters], dtype=np.float64
    )
    distribution_threshold = np.asarray(
        [item.distribution_score_min for item in parameters], dtype=np.float64
    )
    stop_threshold = np.asarray(
        [item.protective_stop_atr for item in parameters], dtype=np.float64
    )
    machines = tuple(
        LifecycleMachine(
            config,
            item,
            anchor_retention_resolver=anchor_retention_resolver,
        )
        for item in parameters
    )

    state = np.full(size, _NEUTRAL, dtype=np.uint8)
    cooldown = np.zeros(size, dtype=np.int16)
    breakout_index = np.full(size, -1, dtype=np.int32)
    holding_days = np.zeros(size, dtype=np.int16)
    distribution_days = np.zeros(size, dtype=np.int8)
    pending_exit = np.zeros(size, dtype=np.bool_)
    active = np.zeros(size, dtype=np.bool_)
    accumulation_at = np.empty(size, dtype=object)
    accumulation_index = np.full(size, -1, dtype=np.int32)
    breakout_at = np.empty(size, dtype=object)
    active_signal_id = np.empty(size, dtype=object)
    accumulation_at.fill(None)
    breakout_at.fill(None)
    active_signal_id.fill(None)
    anchors = _empty_anchors(size)
    root_anchors = _empty_objects(size)
    comparison_anchors = _empty_objects(size)
    working_anchors = _empty_objects(size)
    anchor_chains = _empty_objects(size)

    signals: list[dict[str, Any]] | None = [] if collect_signals else None
    signal_counts: Counter[str] = Counter()
    evaluation_counts: Counter[str] = Counter()
    annual_counts: dict[str, Counter[int]] = {
        item.parameter_id: Counter() for item in parameters
    }
    input_rows = 0
    evaluation_rows = 0
    previous_key: tuple[str, date] | None = None
    symbol: str | None = None
    trading_index = 0

    for raw_record in records:
        record = dict(raw_record)
        assert_no_label_access(record)
        row_symbol = _required_text(record, "symbol")
        trade_date = _date(record.get("trade_date"))
        key = (row_symbol, trade_date)
        if previous_key is not None and key <= previous_key:
            raise ValueError(
                "lattice input must be unique and ordered by symbol/trade_date: "
                f"previous={previous_key}, current={key}"
            )
        previous_key = key
        if symbol != row_symbol:
            if symbol is not None and isinstance(
                anchor_retention_resolver, StreamingLineageSession
            ):
                anchor_retention_resolver.release_symbol(symbol)
            symbol = row_symbol
            trading_index = 0
            state.fill(_NEUTRAL)
            cooldown.fill(0)
            breakout_index.fill(-1)
            holding_days.fill(0)
            distribution_days.fill(0)
            pending_exit.fill(False)
            active.fill(False)
            accumulation_at.fill(None)
            accumulation_index.fill(-1)
            breakout_at.fill(None)
            active_signal_id.fill(None)
            for values in anchors.values():
                values.fill(np.nan)
            root_anchors.fill(None)
            comparison_anchors.fill(None)
            working_anchors.fill(None)
            anchor_chains.fill(None)

        observation = observation_from_record(record, config, panel_snapshot_id)
        _rebase_lattice_for_action(
            observation,
            anchors=anchors,
            comparison_anchors=comparison_anchors,
        )
        is_evaluation = _flag(record.get("is_evaluation_row"))
        input_rows += 1
        evaluation_rows += int(is_evaluation)

        # Exact execution is a downstream gate.  The screening approximation
        # treats the next tradable observation as the fill day and consumes it.
        filled_exit = pending_exit & observation.tradable
        if np.any(filled_exit):
            _clear(filled_exit, state, active, pending_exit, holding_days, distribution_days)
            _clear_anchor_state(
                filled_exit,
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
            cooldown[filled_exit] = config.windows.cooldown
            active_signal_id[filled_exit] = None

        remaining = ~filled_exit
        if observation.corporate_action_blocking or not observation.hard_valid:
            exiting = remaining & active & ~pending_exit
            pending_exit[exiting] = True
            invalid = remaining & ~active
            state[invalid] = _BROKEN
            _clear_anchor_state(
                invalid,
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
        elif observation.tradable:
            open_mask = remaining & active & ~pending_exit
            if np.any(open_mask):
                holding_days[open_mask] += 1
                support = anchors["support"]
                hard_exit = open_mask & (
                    (observation.close < support - stop_threshold * observation.atr)
                    | (holding_days >= config.windows.max_holding)
                )
                lineage_missing = np.zeros(size, dtype=np.bool_)
                anchored_distribution = np.full(size, -np.inf, dtype=np.float64)
                lifecycle_cache: dict[str, tuple[bool, bool, float]] = {}
                for index in np.flatnonzero(open_mask & ~hard_exit):
                    root = _lifecycle_anchor(root_anchors[index], index=index)
                    comparison = _lifecycle_anchor(
                        comparison_anchors[index], index=index
                    )
                    cached = lifecycle_cache.get(root.anchor_id)
                    if cached is None:
                        estimate = exact_anchor_retention(
                            root,
                            observation,
                            resolver=anchor_retention_resolver,
                        )
                        cached = (
                            estimate is not None,
                            chip_structure_broken(
                                root,
                                observation,
                                config.fixed,
                                comparison_anchor=comparison,
                                resolver=anchor_retention_resolver,
                            ),
                            (
                                distribution_score_with_anchor(
                                    root,
                                    observation,
                                    config.fixed,
                                    resolver=anchor_retention_resolver,
                                )
                                if estimate is not None
                                else -np.inf
                            ),
                        )
                        lifecycle_cache[root.anchor_id] = cached
                    has_lineage, anchor_broken, score = cached
                    if not has_lineage:
                        lineage_missing[index] = True
                    elif anchor_broken:
                        hard_exit[index] = True
                    else:
                        anchored_distribution[index] = score
                pending_exit[lineage_missing] = True
                pending_exit[hard_exit] = True
                soft = open_mask & ~hard_exit & ~lineage_missing
                distributing = soft & (
                    anchored_distribution >= distribution_threshold
                )
                distribution_days[soft & ~distributing] = 0
                distribution_days[distributing] += 1
                state[soft & ~distributing] = _ACTIVE
                state[distributing] = _ACTIVE
                confirmed = soft & (
                    distribution_days >= config.windows.exit_confirmation
                )
                pending_exit[confirmed] = True

            eligible = remaining & ~active & ~pending_exit
            cooling = eligible & (cooldown > 0)
            cooldown[cooling] -= 1
            eligible &= ~cooling
            if np.any(eligible):
                _advance_entries(
                    eligible=eligible,
                    state=state,
                    setup=observation.setup_score >= setup_threshold,
                    breakout=observation.breakout_excess_atr >= breakout_threshold,
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
                    parameters=parameters,
                    signals=signals,
                    signal_sink=signal_sink,
                    lifecycle_signal_sink=None,
                    signal_counts=signal_counts,
                    evaluation_counts=evaluation_counts,
                    annual_counts=annual_counts,
                    panel_snapshot_id=panel_snapshot_id,
                    is_evaluation=is_evaluation,
                    anchor_retention_resolver=anchor_retention_resolver,
                )
        if observation.tradable:
            trading_index += 1

    if symbol is not None and isinstance(
        anchor_retention_resolver, StreamingLineageSession
    ):
        anchor_retention_resolver.release_symbol(symbol)

    return EntryLatticeResult(
        parameters=parameters,
        signals=tuple(signals or ()),
        input_rows=input_rows,
        evaluation_rows=evaluation_rows,
        panel_passes=1,
        signal_counts={
            item.parameter_id: signal_counts[item.parameter_id] for item in parameters
        },
        evaluation_signal_counts={
            item.parameter_id: evaluation_counts[item.parameter_id]
            for item in parameters
        },
        annual_evaluation_signal_counts={
            parameter_id: dict(counts) for parameter_id, counts in annual_counts.items()
        },
    )


def screen_entry_lattice_files(
    files: Sequence[Path],
    config: MarkupRetestConfig,
    *,
    panel_snapshot_id: str,
    threads: int | None = None,
    collect_signals: bool = False,
) -> EntryLatticeResult:
    """Screen a partitioned panel once while parallelizing independent symbols.

    Panel files are partitioned by a stable symbol bucket.  A stock never
    crosses buckets, so each worker can advance complete lifecycle state for
    its stocks without communication.  The parent process only adds counts
    and deterministically merges optional signal rows; no parameter decision
    is made inside a worker.
    """

    groups = _group_panel_files(files)
    if not groups:
        raise ValueError("entry lattice requires at least one panel parquet file")
    requested_workers = threads if threads is not None else (os.cpu_count() or 1)
    worker_count = min(max(requested_workers, 1), 10, len(groups))
    arguments = tuple(
        (
            group,
            config,
            panel_snapshot_id,
            config.assets.chip_lineage_root,
            collect_signals,
        )
        for group in groups
    )
    if worker_count == 1:
        results = tuple(_screen_entry_lattice_group(item) for item in arguments)
    else:
        with ProcessPoolExecutor(max_workers=worker_count) as executor:
            results = tuple(executor.map(_screen_entry_lattice_group, arguments))
    return _merge_entry_lattice_results(results, collect_signals=collect_signals)


def _screen_entry_lattice_group(
    arguments: tuple[
        tuple[Path, ...],
        MarkupRetestConfig,
        str,
        Path | None,
        bool,
    ],
) -> EntryLatticeResult:
    files, config, panel_snapshot_id, lineage_root, collect_signals = arguments
    return screen_entry_lattice(
        stream_panel(files),
        config,
        panel_snapshot_id=panel_snapshot_id,
        collect_signals=collect_signals,
        anchor_retention_resolver=(
            StreamingLineageSession(lineage_root)
            if lineage_root is not None
            else None
        ),
    )


def _merge_entry_lattice_results(
    results: Sequence[EntryLatticeResult],
    *,
    collect_signals: bool,
) -> EntryLatticeResult:
    if not results:
        raise ValueError("cannot merge an empty entry lattice result set")
    parameters = results[0].parameters
    parameter_ids = tuple(item.parameter_id for item in parameters)
    for result in results[1:]:
        if tuple(item.parameter_id for item in result.parameters) != parameter_ids:
            raise ValueError("parallel entry lattice workers used different parameters")
    signals = (
        tuple(
            sorted(
                (row for result in results for row in result.signals),
                key=lambda row: (
                    str(row["parameter_id"]),
                    str(row["symbol"]),
                    str(row["decision_at"]),
                ),
            )
        )
        if collect_signals
        else ()
    )
    return EntryLatticeResult(
        parameters=parameters,
        signals=signals,
        input_rows=sum(result.input_rows for result in results),
        evaluation_rows=sum(result.evaluation_rows for result in results),
        panel_passes=1,
        signal_counts={
            parameter_id: sum(
                int(result.signal_counts.get(parameter_id, 0)) for result in results
            )
            for parameter_id in parameter_ids
        },
        evaluation_signal_counts={
            parameter_id: sum(
                int(result.evaluation_signal_counts.get(parameter_id, 0))
                for result in results
            )
            for parameter_id in parameter_ids
        },
        annual_evaluation_signal_counts={
            parameter_id: {
                year: sum(
                    int(
                        result.annual_evaluation_signal_counts
                        .get(parameter_id, {})
                        .get(year, 0)
                    )
                    for result in results
                )
                for year in sorted(
                    {
                        year
                        for result in results
                        for year in result.annual_evaluation_signal_counts
                        .get(parameter_id, {})
                    }
                )
            }
            for parameter_id in parameter_ids
        },
    )


def _group_panel_files(files: Sequence[Path]) -> tuple[tuple[Path, ...], ...]:
    grouped: dict[str, list[Path]] = {}
    for path in files:
        bucket = next(
            (
                part.partition("=")[2]
                for part in path.parts
                if part.startswith("symbol_bucket=")
            ),
            "unpartitioned",
        )
        grouped.setdefault(bucket, []).append(path)
    return tuple(tuple(sorted(grouped[bucket])) for bucket in sorted(grouped))


def shortlist_entry_candidates(
    result: EntryLatticeResult,
    config: MarkupRetestConfig,
    *,
    evaluation_years: tuple[int, ...] = (2021, 2022, 2023),
    limit: int = 5,
) -> EntryShortlistResult:
    """Apply the declared annual-frequency gate and retain at most five entries.

    This is parameter-combination screening, not a Top-N signal filter: every
    qualifying stock signal remains in the output.  The lexicographic tie
    break prefers a passing local threshold region, stable annual counts and
    finally the centre of the declared grid.  It never reads future returns.
    """

    if not evaluation_years or tuple(sorted(set(evaluation_years))) != evaluation_years:
        raise ValueError("evaluation_years must be unique and increasing")
    if limit < 1 or limit > 5:
        raise ValueError("entry shortlist limit must be between 1 and 5")
    expected = entry_parameter_grid(config)
    if tuple(item.parameter_id for item in result.parameters) != tuple(
        item.parameter_id for item in expected
    ):
        raise ValueError("entry lattice parameters do not match the configured 81-grid")

    preliminary: dict[str, tuple[Mapping[int, int], float, tuple[str, ...]]] = {}
    for parameters in result.parameters:
        raw = result.annual_evaluation_signal_counts.get(parameters.parameter_id, {})
        counts = {year: int(raw.get(year, 0)) for year in evaluation_years}
        mean = sum(counts.values()) / len(evaluation_years)
        reasons: list[str] = []
        if any(
            value < config.quality.annual_signal_min
            or value > config.quality.annual_signal_max
            for value in counts.values()
        ):
            reasons.append("ANNUAL_SIGNAL_COUNT_OUT_OF_RANGE")
        if not config.quality.mean_signal_min <= mean <= config.quality.mean_signal_max:
            reasons.append("MEAN_SIGNAL_COUNT_OUT_OF_RANGE")
        preliminary[parameters.parameter_id] = (counts, mean, tuple(reasons))

    trials: list[EntryFrequencyTrial] = []
    for parameters in result.parameters:
        trial_counts, trial_mean, trial_reasons = preliminary[parameters.parameter_id]
        adjacent_passes = sum(
            not preliminary[neighbor.parameter_id][2]
            for neighbor in _entry_neighbors(parameters, result.parameters, config)
        )
        target = (config.quality.mean_signal_min + config.quality.mean_signal_max) / 2.0
        trials.append(
            EntryFrequencyTrial(
                parameter_id=parameters.parameter_id,
                parameters=parameters,
                annual_signal_counts=trial_counts,
                mean_annual_signals=trial_mean,
                worst_target_deviation=max(
                    abs(value - target) for value in trial_counts.values()
                ),
                adjacent_frequency_passes=adjacent_passes,
                frequency_gate="PASS" if not trial_reasons else "FAIL",
                reason_codes=trial_reasons,
            )
        )

    passing = [trial for trial in trials if trial.frequency_gate == "PASS"]
    passing.sort(
        key=lambda trial: (
            -trial.adjacent_frequency_passes,
            trial.worst_target_deviation,
            _entry_grid_centrality(trial.parameters, config),
            trial.parameter_id,
        )
    )
    candidates = tuple(trial.parameters for trial in passing[:limit])
    status = "PASS" if candidates else "FAIL"
    shortlist_reasons = (
        () if candidates else ("NO_ENTRY_COMBINATION_PASSES_FREQUENCY_GATE",)
    )
    return EntryShortlistResult(
        evaluation_years=evaluation_years,
        trials=tuple(trials),
        candidates=candidates,
        status=status,
        reason_codes=shortlist_reasons,
    )


def persist_entry_frequency_trials(
    shortlist: EntryShortlistResult,
    config: MarkupRetestConfig,
    *,
    panel_snapshot_id: str,
    ledger: TrialLedger | None = None,
) -> TrialLedgerWriteResult:
    """Append all 81 frequency trials and their shortlist idempotently."""

    target = ledger or TrialLedger(config.trial_ledger)
    run_id = hashlib.sha256(
        f"ENTRY_FREQUENCY_V1|{config.sha256}|{panel_snapshot_id}".encode()
    ).hexdigest()
    payloads: list[tuple[str, dict[str, Any]]] = []
    for trial in shortlist.trials:
        trial_id = hashlib.sha256(
            f"{run_id}|{trial.parameter_id}".encode()
        ).hexdigest()
        payloads.append(
            (
                "ENTRY_FREQUENCY_TRIAL",
                {
                    "event_id": trial_id,
                    "run_id": run_id,
                    "strategy_version": config.strategy_version,
                    "config_sha256": config.sha256,
                    "panel_snapshot_id": panel_snapshot_id,
                    "parameter_id": trial.parameter_id,
                    "parameters": trial.parameters.canonical(),
                    "evaluation_years": list(shortlist.evaluation_years),
                    "annual_signal_counts": {
                        str(year): count
                        for year, count in trial.annual_signal_counts.items()
                    },
                    "mean_annual_signals": trial.mean_annual_signals,
                    "worst_target_deviation": trial.worst_target_deviation,
                    "adjacent_frequency_passes": trial.adjacent_frequency_passes,
                    "frequency_gate": trial.frequency_gate,
                    "reason_codes": list(trial.reason_codes),
                },
            )
        )
    shortlist_id = hashlib.sha256(f"{run_id}|SHORTLIST".encode()).hexdigest()
    payloads.append(
        (
            "ENTRY_FREQUENCY_SHORTLIST",
            {
                "event_id": shortlist_id,
                "run_id": run_id,
                "strategy_version": config.strategy_version,
                "config_sha256": config.sha256,
                "panel_snapshot_id": panel_snapshot_id,
                "evaluation_years": list(shortlist.evaluation_years),
                "candidate_parameter_ids": [
                    item.parameter_id for item in shortlist.candidates
                ],
                "status": shortlist.status,
                "reason_codes": list(shortlist.reason_codes),
            },
        )
    )

    existing_by_id: dict[str, tuple[str, Mapping[str, Any]]] = {}
    for entry in target.read_verified():
        event_id = entry.payload.get("event_id")
        if isinstance(event_id, str):
            existing_by_id[event_id] = (entry.event_type, entry.payload)
    appended = 0
    existing = 0
    for event_type, payload in payloads:
        event_id = str(payload["event_id"])
        prior = existing_by_id.get(event_id)
        if prior is not None:
            if prior != (event_type, payload):
                raise ValueError(f"trial ledger event_id collision: {event_id}")
            existing += 1
            continue
        target.append(event_type, payload)
        existing_by_id[event_id] = (event_type, payload)
        appended += 1
    return TrialLedgerWriteResult(
        run_id=run_id,
        appended=appended,
        existing=existing,
        ledger_path=target.path,
    )


def _advance_entries(
    *,
    eligible: npt.NDArray[np.bool_],
    state: npt.NDArray[np.uint8],
    setup: npt.NDArray[np.bool_],
    breakout: npt.NDArray[np.bool_],
    retest_depth_threshold: npt.NDArray[np.float64],
    migration_threshold: npt.NDArray[np.float64],
    observation: LifecycleObservation,
    trading_index: int,
    config: MarkupRetestConfig,
    cooldown: npt.NDArray[np.int16],
    accumulation_at: npt.NDArray[np.object_],
    accumulation_index: npt.NDArray[np.int32],
    breakout_at: npt.NDArray[np.object_],
    breakout_index: npt.NDArray[np.int32],
    anchors: Mapping[str, npt.NDArray[np.float64]],
    root_anchors: npt.NDArray[np.object_],
    comparison_anchors: npt.NDArray[np.object_],
    working_anchors: npt.NDArray[np.object_],
    anchor_chains: npt.NDArray[np.object_],
    active: npt.NDArray[np.bool_],
    active_signal_id: npt.NDArray[np.object_],
    machines: tuple[LifecycleMachine, ...],
    parameters: tuple[StrategyParameters, ...],
    signals: list[dict[str, Any]] | None,
    signal_sink: SignalSink | None,
    lifecycle_signal_sink: LifecycleSignalSink | None,
    signal_counts: Counter[str],
    evaluation_counts: Counter[str],
    annual_counts: Mapping[str, Counter[int]],
    panel_snapshot_id: str,
    is_evaluation: bool,
    anchor_retention_resolver: AnchorRetentionResolver | None,
) -> None:
    neutral = eligible & ((state == _NEUTRAL) | (state == _BROKEN))
    start = neutral & setup
    state[neutral & ~setup] = _NEUTRAL
    state[start] = _ACCUMULATING
    accumulation_at[start] = observation.decision_at.date()
    accumulation_index[start] = trading_index
    if np.any(start):
        root = freeze_lifecycle_anchor(
            observation, strategy_version=config.strategy_version
        )
        for index in np.flatnonzero(start):
            root_anchors[index] = root
            comparison_anchors[index] = root
            working_anchors[index] = root
            anchor_chains[index] = (root,)

    accumulating = eligible & (state == _ACCUMULATING) & ~start
    stale = accumulating & (
        trading_index - accumulation_index > config.windows.accumulation * 3
    )
    state[stale] = _NEUTRAL
    if np.any(stale):
        _clear_anchor_state(
            stale,
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
    accumulating &= ~stale
    broke_out = accumulating & breakout
    if np.any(broke_out):
        state[broke_out] = _BREAKOUT
        breakout_at[broke_out] = observation.decision_at.date()
        breakout_index[broke_out] = trading_index
        anchors["support"][broke_out] = observation.structure_support
        anchors["atr"][broke_out] = observation.atr
        anchors["volume"][broke_out] = observation.volume
        anchors["turnover"][broke_out] = observation.turnover
        anchors["average_cost"][broke_out] = observation.prior_average_cost
        anchors["cost_p50"][broke_out] = observation.prior_cost_p50

    retesting = eligible & (state == _BREAKOUT) & ~broke_out
    broken = retesting & (
        observation.close < anchors["support"] - 1.5 * observation.atr
    )
    structure_cache: dict[str, bool] = {}
    for index in np.flatnonzero(retesting & ~broken):
        root = _lifecycle_anchor(root_anchors[index], index=index)
        comparison = _lifecycle_anchor(comparison_anchors[index], index=index)
        anchor_broken = structure_cache.get(root.anchor_id)
        if anchor_broken is None:
            anchor_broken = chip_structure_broken(
                root,
                observation,
                config.fixed,
                comparison_anchor=comparison,
                resolver=anchor_retention_resolver,
            )
            structure_cache[root.anchor_id] = anchor_broken
        broken[index] = anchor_broken
    state[broken] = _BROKEN
    expired = retesting & ~broken & (
        trading_index - breakout_index > config.windows.retest_max
    )
    state[expired] = _NEUTRAL
    reset = broken | expired
    cooldown[reset] = config.windows.cooldown
    if np.any(reset):
        _clear_anchor_state(
            reset,
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
    elapsed = trading_index - breakout_index
    ready = retesting & ~broken & ~expired & (elapsed >= config.windows.retest_min)
    if not np.any(ready):
        return
    retest_depth = np.abs(anchors["support"] - observation.low) / observation.atr
    migration = np.minimum(
        observation.average_cost - anchors["average_cost"],
        observation.cost_p50 - anchors["cost_p50"],
    ) / observation.atr
    frozen_support_regained = (
        observation.close
        >= anchors["support"]
        - config.fixed.support_tolerance_atr * observation.atr
    ) & (observation.close_vs_vwap >= 0)
    preliminarily_qualified = ready & (
        (retest_depth <= retest_depth_threshold)
        & (migration >= migration_threshold)
        & (
            observation.volume
            / np.maximum(anchors["volume"], 1e-12)
            <= config.fixed.retest_volume_ratio_max
        )
        & (
            observation.turnover
            / np.maximum(anchors["turnover"], 1e-12)
            <= config.fixed.retest_turnover_ratio_max
        )
        & frozen_support_regained
        & observation.downside_absorption
        & (
            observation.chip_model_disagreement_atr
            <= config.fixed.max_model_disagreement_atr
        )
        & (observation.market_state in {"RISK_ON", "NEUTRAL"})
        & (observation.sector_state in {"STRONG", "NEUTRAL"})
    )
    qualified = np.zeros_like(ready)
    retention_cache: dict[str, AnchorRetentionEstimate | None] = {}
    for index in np.flatnonzero(preliminarily_qualified):
        root = _lifecycle_anchor(root_anchors[index], index=index)
        if root.anchor_id not in retention_cache:
            retention_cache[root.anchor_id] = exact_anchor_retention(
                root,
                observation,
                resolver=anchor_retention_resolver,
            )
        estimate = retention_cache[root.anchor_id]
        if estimate is not None and estimate.lower >= config.fixed.anchor_retention_floor:
            qualified[index] = True
    support_cache: dict[str, LifecycleAnchor | None] = {}
    for index in np.flatnonzero(qualified):
        root = _lifecycle_anchor(root_anchors[index], index=index)
        comparison = _lifecycle_anchor(comparison_anchors[index], index=index)
        working = _lifecycle_anchor(working_anchors[index], index=index)
        chain = _anchor_chain(anchor_chains[index], index=index)
        estimate = exact_anchor_retention(
            root,
            observation,
            resolver=anchor_retention_resolver,
        )
        if estimate is None:
            raise ValueError("qualified entry is missing exact anchor lineage")
        memory = LifecycleMemory(
            state=ChipLifecycleState.BREAKOUT,
            accumulation_started_at=accumulation_at[index],
            accumulation_index=int(accumulation_index[index]),
            accumulation_anchor=root,
            comparison_anchor=comparison,
            working_anchor=working,
            anchor_chain=chain,
            breakout_at=breakout_at[index],
            breakout_support=float(anchors["support"][index]),
            breakout_atr=float(anchors["atr"][index]),
            breakout_volume=float(anchors["volume"][index]),
            breakout_turnover=float(anchors["turnover"][index]),
            pre_breakout_average_cost=float(anchors["average_cost"][index]),
            pre_breakout_cost_p50=float(anchors["cost_p50"][index]),
            breakout_index=int(breakout_index[index]),
        )
        if root.anchor_id not in support_cache:
            support_cache[root.anchor_id] = maybe_create_support_anchor(
                memory, observation, estimate, config.fixed
            )
        support_anchor = support_cache[root.anchor_id]
        if support_anchor is not None:
            memory = replace(
                memory,
                working_anchor=support_anchor,
                anchor_chain=(*chain, support_anchor),
            )
            working_anchors[index] = support_anchor
            anchor_chains[index] = memory.anchor_chain
        signal = machines[index].create_signal(memory, observation)
        row = serialize_signal(
            signal,
            panel_snapshot_id=panel_snapshot_id,
            is_evaluation=is_evaluation,
        )
        state[index] = _ACTIVE
        active[index] = True
        active_signal_id[index] = signal.signal_id
        if signals is not None:
            signals.append(row)
        if signal_sink is not None:
            signal_sink(row)
        if lifecycle_signal_sink is not None:
            lifecycle_signal_sink(index, signal)
        parameter_id = parameters[index].parameter_id
        signal_counts[parameter_id] += 1
        if is_evaluation:
            evaluation_counts[parameter_id] += 1
            annual_counts[parameter_id][observation.decision_at.year] += 1


def _entry_neighbors(
    parameters: StrategyParameters,
    grid: tuple[StrategyParameters, ...],
    config: MarkupRetestConfig,
) -> tuple[StrategyParameters, ...]:
    """Return direct one-step neighbours in the four-dimensional entry grid."""

    dimensions = (
        "setup_score_min",
        "breakout_buffer_atr",
        "max_retest_depth_atr",
        "min_cost_migration_atr",
    )
    indexes = {
        name: {
            float(value): index
            for index, value in enumerate(config.parameter_grids[name])
        }
        for name in dimensions
    }
    current = {
        name: indexes[name][float(getattr(parameters, name))]
        for name in dimensions
    }
    return tuple(
        candidate
        for candidate in grid
        if sum(
            abs(
                indexes[name][float(getattr(candidate, name))]
                - current[name]
            )
            for name in dimensions
        )
        == 1
    )


def _entry_grid_centrality(
    parameters: StrategyParameters,
    config: MarkupRetestConfig,
) -> float:
    """Return Manhattan distance from the centre of the entry lattice."""

    distance = 0.0
    for name in (
        "setup_score_min",
        "breakout_buffer_atr",
        "max_retest_depth_atr",
        "min_cost_migration_atr",
    ):
        values = tuple(float(value) for value in config.parameter_grids[name])
        index = values.index(float(getattr(parameters, name)))
        distance += abs(index - (len(values) - 1) / 2.0)
    return distance


def _empty_anchors(size: int) -> dict[str, npt.NDArray[np.float64]]:
    return {
        name: np.full(size, np.nan, dtype=np.float64)
        for name in (
            "support",
            "atr",
            "volume",
            "turnover",
            "average_cost",
            "cost_p50",
        )
    }


def _empty_objects(size: int) -> npt.NDArray[np.object_]:
    values = np.empty(size, dtype=object)
    values.fill(None)
    return values


def _rebase_lattice_for_action(
    observation: LifecycleObservation,
    *,
    anchors: Mapping[str, npt.NDArray[np.float64]],
    comparison_anchors: npt.NDArray[np.object_],
) -> None:
    multiplier = observation.share_multiplier
    cash = observation.cash_per_share
    if multiplier == 1.0 and cash == 0.0:
        return
    for index, value in enumerate(comparison_anchors):
        if isinstance(value, LifecycleAnchor):
            comparison_anchors[index] = rebase_comparison_anchor(
                value,
                share_multiplier=multiplier,
                cash_per_share=cash,
            )
    for name in ("support", "average_cost", "cost_p50"):
        values = anchors[name]
        present = np.isfinite(values)
        values[present] = (values[present] - cash) / multiplier
        if np.any(values[present] <= 0):
            raise ValueError("corporate action produced a non-positive lattice price")
    atr = anchors["atr"]
    atr[np.isfinite(atr)] /= multiplier
    volume = anchors["volume"]
    volume[np.isfinite(volume)] *= multiplier


def _clear_anchor_state(
    mask: npt.NDArray[np.bool_],
    *,
    accumulation_at: npt.NDArray[np.object_],
    accumulation_index: npt.NDArray[np.int32],
    breakout_at: npt.NDArray[np.object_],
    breakout_index: npt.NDArray[np.int32],
    anchors: Mapping[str, npt.NDArray[np.float64]],
    root_anchors: npt.NDArray[np.object_],
    comparison_anchors: npt.NDArray[np.object_],
    working_anchors: npt.NDArray[np.object_],
    anchor_chains: npt.NDArray[np.object_],
) -> None:
    accumulation_at[mask] = None
    accumulation_index[mask] = -1
    breakout_at[mask] = None
    breakout_index[mask] = -1
    for values in anchors.values():
        values[mask] = np.nan
    root_anchors[mask] = None
    comparison_anchors[mask] = None
    working_anchors[mask] = None
    anchor_chains[mask] = None


def _lifecycle_anchor(value: object, *, index: int) -> LifecycleAnchor:
    if not isinstance(value, LifecycleAnchor):
        raise ValueError(f"lifecycle lattice index {index} has no frozen anchor")
    return value


def _anchor_chain(value: object, *, index: int) -> tuple[LifecycleAnchor, ...]:
    if not isinstance(value, tuple) or not value or not all(
        isinstance(item, LifecycleAnchor) for item in value
    ):
        raise ValueError(f"lifecycle lattice index {index} has no valid anchor chain")
    return value


def _clear(
    mask: npt.NDArray[np.bool_],
    state: npt.NDArray[np.uint8],
    active: npt.NDArray[np.bool_],
    pending_exit: npt.NDArray[np.bool_],
    holding_days: npt.NDArray[np.int16],
    distribution_days: npt.NDArray[np.int8],
) -> None:
    state[mask] = _NEUTRAL
    active[mask] = False
    pending_exit[mask] = False
    holding_days[mask] = 0
    distribution_days[mask] = 0


def _required_text(record: Mapping[str, object], field: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value[:10])
    raise ValueError("trade_date must be a date or ISO date string")


def _flag(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, np.integer)) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str) and value.lower() in {"true", "false"}:
        return value.lower() == "true"
    raise ValueError(f"expected boolean value, got {value!r}")
