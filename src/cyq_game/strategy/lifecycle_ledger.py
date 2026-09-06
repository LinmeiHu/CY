"""Deterministic post-hoc lifecycle, entry, and exit replay ledger.

The ledger is a sibling audit artifact.  It calls the canonical lifecycle and
execution engines and never changes chip shards, strategy thresholds, or fill
rules.  Rows are canonical JSON so the same frozen replay envelope produces
the same content digest and bytes.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path
from typing import Any, cast

from cyq_game.domain import ChipLifecycleState, ExitReason
from cyq_game.strategy.exact_replay import (
    _action_coordinate_mismatch,
    _first_action_coordinate_mismatch,
)
from cyq_game.strategy.execution import (
    EntryExecution,
    EntryExecutionStatus,
    ExecutionAttempt,
    ExecutionReason,
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
    LifecycleAnchor,
    LifecycleMachine,
    LifecycleMemory,
    LifecycleObservation,
    MarkupRetestConfig,
    StrategyParameters,
    StrategySignal,
    TransitionResult,
    chip_structure_broken,
    distribution_score_with_anchor,
    exact_anchor_retention,
    rebase_lifecycle_memory,
)
from cyq_game.strategy.signals import (
    _DISTRIBUTION_EVIDENCE,
    _SETUP_EVIDENCE,
    observation_from_record,
)

LEDGER_SCHEMA_VERSION = "v12-lifecycle-entry-ledger-v1"
DECISION_TABLE = "decisions.jsonl"
EXECUTION_TABLE = "execution_attempts.jsonl"
MANIFEST_FILE = "manifest.json"


@dataclass(frozen=True)
class LifecycleLedgerProvenance:
    """Immutable replay envelope referenced by every ledger row."""

    v3_root_manifest_sha256: str
    v3_root_id: str
    code_commit: str
    semantic_fingerprint: str
    chip_artifact_fingerprint: str
    replay_parameter_digest: str
    panel_snapshot_id: str
    semantic_epoch: str
    code_file_sha256: Mapping[str, str]
    symbol_manifest_sha256: Mapping[str, str]
    input_manifest_sha256: Mapping[str, str]

    def __post_init__(self) -> None:
        required = (
            self.v3_root_manifest_sha256,
            self.v3_root_id,
            self.code_commit,
            self.semantic_fingerprint,
            self.chip_artifact_fingerprint,
            self.replay_parameter_digest,
            self.panel_snapshot_id,
            self.semantic_epoch,
        )
        if any(not value for value in required):
            raise ValueError("lifecycle ledger provenance cannot be empty")

    def canonical(self) -> dict[str, Any]:
        return {
            "v3_root_manifest_sha256": self.v3_root_manifest_sha256,
            "v3_root_id": self.v3_root_id,
            "code_commit": self.code_commit,
            "semantic_fingerprint": self.semantic_fingerprint,
            "chip_artifact_fingerprint": self.chip_artifact_fingerprint,
            "replay_parameter_digest": self.replay_parameter_digest,
            "panel_snapshot_id": self.panel_snapshot_id,
            "semantic_epoch": self.semantic_epoch,
            "code_file_sha256": dict(sorted(self.code_file_sha256.items())),
            "symbol_manifest_sha256": dict(sorted(self.symbol_manifest_sha256.items())),
            "input_manifest_sha256": dict(sorted(self.input_manifest_sha256.items())),
        }

    def for_symbol(self, symbol: str) -> dict[str, Any]:
        if symbol not in self.symbol_manifest_sha256:
            raise ValueError(f"missing V3 symbol-manifest binding for {symbol}")
        if symbol not in self.input_manifest_sha256:
            raise ValueError(f"missing input-manifest binding for {symbol}")
        return {
            "v3_root_manifest_sha256": self.v3_root_manifest_sha256,
            "v3_root_id": self.v3_root_id,
            "v3_symbol_manifest_sha256": self.symbol_manifest_sha256[symbol],
            "input_manifest_sha256": self.input_manifest_sha256[symbol],
            "code_commit": self.code_commit,
            "semantic_fingerprint": self.semantic_fingerprint,
            "chip_artifact_fingerprint": self.chip_artifact_fingerprint,
            "replay_parameter_digest": self.replay_parameter_digest,
            "panel_snapshot_id": self.panel_snapshot_id,
            "semantic_epoch": self.semantic_epoch,
            "code_file_sha256": dict(sorted(self.code_file_sha256.items())),
        }


@dataclass(frozen=True)
class LifecycleLedgerReplay:
    provenance: LifecycleLedgerProvenance
    parameter_id: str
    decisions: tuple[dict[str, Any], ...]
    execution_attempts: tuple[dict[str, Any], ...]

    @property
    def canonical_digest(self) -> str:
        return _digest(
            {
                "schema_version": LEDGER_SCHEMA_VERSION,
                "provenance": self.provenance.canonical(),
                "parameter_id": self.parameter_id,
                "decisions": self.decisions,
                "execution_attempts": self.execution_attempts,
            }
        )


@dataclass(frozen=True)
class LifecycleLedgerArtifact:
    path: Path
    manifest_path: Path
    canonical_digest: str
    decision_rows: int
    execution_attempt_rows: int


@dataclass
class _Position:
    signal: StrategySignal
    entry: EntryExecution
    quantity: int


@dataclass(frozen=True)
class _PendingEntry:
    signal: StrategySignal
    execution: EntryExecution


@dataclass(frozen=True)
class _PendingExit:
    intent: ExitIntent
    execution: ExitExecution


@dataclass
class _ExecutionBinding:
    side: str
    signal: StrategySignal
    root_anchor: LifecycleAnchor
    rolling_base: dict[str, Any]
    execution: EntryExecution | ExitExecution
    intent: ExitIntent | None = None


def replay_lifecycle_entry_ledger(
    records: Iterable[Mapping[str, object]],
    windows: Sequence[ExecutionWindow],
    market_trading_dates: Sequence[date],
    config: MarkupRetestConfig,
    parameters: StrategyParameters,
    provenance: LifecycleLedgerProvenance,
    *,
    anchor_retention_resolver: AnchorRetentionResolver | None = None,
) -> LifecycleLedgerReplay:
    """Replay one ordered symbol with the production scalar strategy engines."""

    raw_records = [dict(record) for record in records]
    if not raw_records:
        return LifecycleLedgerReplay(provenance, parameters.parameter_id, (), ())
    ordered_dates = tuple(sorted(dict.fromkeys(market_trading_dates)))
    ordered_windows = tuple(
        sorted(
            windows,
            key=lambda item: (
                item.symbol,
                item.trade_date,
                item.window_index,
                item.available_at,
            ),
        )
    )
    first_broken_date = _first_action_coordinate_mismatch(raw_records)
    if first_broken_date is not None:
        ordered_windows = tuple(
            replace(window, corporate_action_blocking=True)
            if window.trade_date >= first_broken_date
            else window
            for window in ordered_windows
        )

    machine = LifecycleMachine(
        config,
        parameters,
        anchor_retention_resolver=anchor_retention_resolver,
    )
    memory = LifecycleMemory()
    position: _Position | None = None
    pending_entry: _PendingEntry | None = None
    pending_exit: _PendingExit | None = None
    decisions: list[dict[str, Any]] = []
    execution_bindings: list[_ExecutionBinding] = []
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
            reasons = [item for item in str(record.get("reason_codes") or "").split("|") if item]
            reasons.append("ACTION_PRICE_COORDINATE_MISMATCH")
            record.update(
                {
                    "research_hard_valid": False,
                    "corporate_action_blocking": bool(record.get("corporate_action_blocking"))
                    or mismatch,
                    "share_multiplier": 1.0,
                    "cash_per_share": 0.0,
                    "reason_codes": "|".join(dict.fromkeys(reasons)),
                }
            )
        observation = observation_from_record(record, config, provenance.panel_snapshot_id)
        trade_date = _as_date(record.get("trade_date"), field="trade_date")
        if symbol is None:
            symbol = observation.symbol
        elif observation.symbol != symbol:
            raise ValueError(
                "one lifecycle ledger replay cannot contain multiple symbols: "
                f"{symbol}, {observation.symbol}"
            )
        if previous_date is not None and trade_date <= previous_date:
            raise ValueError("lifecycle ledger input must be unique and ordered by trade date")
        previous_date = trade_date

        before = memory
        transition: TransitionResult | None = None
        phase: str | None = None
        signal: StrategySignal | None = None
        entry_execution: EntryExecution | None = None
        actual_entry = False
        exit_intent: ExitIntent | None = None
        actual_exit: ExitExecution | None = None
        lifecycle_termination_reason: str | None = None

        observation_valid = (
            observation.hard_valid
            and not observation.corporate_action_blocking
            and observation.peak_identity_valid
        )
        if observation_valid and position is not None:
            _apply_position_action(position, observation, trade_date)

        handled = False
        if pending_entry is not None:
            pending_entry_execution = pending_entry.execution
            if not observation_valid:
                memory = machine.advance(memory, observation, trading_index=0).memory
                phase = "ENTRY_CANCELLED_INVALID"
                lifecycle_termination_reason = "ENTRY_CANCELLED_INVALID"
                pending_entry = None
                handled = True
            elif pending_entry_execution.status == EntryExecutionStatus.FILLED:
                fill_date = _required_datetime(
                    pending_entry_execution.fill_at, "entry fill_at"
                ).date()
                if trade_date < fill_date:
                    memory = rebase_lifecycle_memory(memory, observation)
                    phase = "ENTRY_PENDING"
                    handled = True
                elif trade_date > fill_date:
                    raise RuntimeError(
                        f"daily panel is missing entry fill date {fill_date} for {symbol}"
                    )
                else:
                    position = _Position(
                        signal=pending_entry.signal,
                        entry=pending_entry_execution,
                        quantity=pending_entry_execution.quantity,
                    )
                    pending_entry = None
                    actual_entry = True
            elif pending_entry_execution.status == EntryExecutionStatus.FAILED:
                if not pending_entry_execution.attempted_trading_dates:
                    raise RuntimeError("failed entry has no attempted trading dates")
                terminal_date = pending_entry_execution.attempted_trading_dates[-1]
                if trade_date < terminal_date:
                    memory = rebase_lifecycle_memory(memory, observation)
                    phase = "ENTRY_PENDING"
                elif trade_date > terminal_date:
                    raise RuntimeError(
                        f"daily panel is missing entry failure date {terminal_date} for {symbol}"
                    )
                else:
                    memory = machine.after_exit()
                    phase = "ENTRY_EXECUTION_FAILED"
                    lifecycle_termination_reason = "ENTRY_EXECUTION_FAILED"
                    pending_entry = None
                handled = True
            elif pending_entry_execution.status == EntryExecutionStatus.PENDING:
                memory = rebase_lifecycle_memory(memory, observation)
                phase = "ENTRY_PENDING"
                handled = True
            else:
                raise RuntimeError(
                    "unexpected pending entry status: "
                    f"{pending_entry_execution.status}"
                )

        if not handled and pending_exit is not None:
            pending_exit_execution = pending_exit.execution
            if pending_exit_execution.status == ExitExecutionStatus.FILLED:
                fill_date = _required_datetime(
                    pending_exit_execution.fill_at, "exit fill_at"
                ).date()
                if trade_date < fill_date:
                    memory = machine.advance(memory, observation, trading_index=0).memory
                    phase = "EXIT_PENDING"
                elif trade_date > fill_date:
                    raise RuntimeError(
                        f"daily panel is missing exit fill date {fill_date} for {symbol}"
                    )
                else:
                    if position is None:
                        raise RuntimeError("pending exit has no filled position")
                    adjusted_intent = replace(pending_exit.intent, quantity=position.quantity)
                    exact_fill = execute_exit(
                        adjusted_intent,
                        ordered_windows,
                        market_trading_dates=ordered_dates,
                        settings=config.execution,
                    )
                    if (
                        exact_fill.status != ExitExecutionStatus.FILLED
                        or exact_fill.fill_at != pending_exit_execution.fill_at
                    ):
                        raise RuntimeError(
                            "corporate-action quantity reconciliation changed exit timing"
                        )
                    _replace_exit_binding(
                        execution_bindings, pending_exit.intent.intent_id, exact_fill
                    )
                    actual_exit = exact_fill
                    lifecycle_termination_reason = pending_exit.intent.reason.value
                    memory = machine.after_exit()
                    position = None
                    pending_exit = None
                    phase = "EXIT_FILLED"
                handled = True
            elif pending_exit_execution.status in {
                ExitExecutionStatus.PENDING,
                ExitExecutionStatus.BLOCKED_INTENT,
            }:
                memory = machine.advance(memory, observation, trading_index=0).memory
                phase = "EXIT_PENDING"
                handled = True
            else:
                raise RuntimeError(
                    f"unexpected pending exit status: {pending_exit_execution.status}"
                )

        if not handled:
            transition = machine.advance(memory, observation, trading_index=trading_index)
            memory = transition.memory
            signal = transition.signal
            if signal is not None:
                entry_execution = execute_entry(
                    signal,
                    ordered_windows,
                    market_trading_dates=ordered_dates,
                    settings=config.execution,
                    scope=ExecutionScope.RESEARCH_EVENT_STUDY,
                )
                root = memory.accumulation_anchor
                if root is None:
                    raise RuntimeError("qualified signal lost its immutable root anchor")
                execution_bindings.append(
                    _ExecutionBinding(
                        side="ENTRY",
                        signal=signal,
                        root_anchor=root,
                        rolling_base=_rolling_base(record, observation),
                        execution=entry_execution,
                    )
                )
                if entry_execution.status == EntryExecutionStatus.BLOCKED_SIGNAL:
                    memory = machine.after_exit()
                    lifecycle_termination_reason = "ENTRY_SIGNAL_BLOCKED"
                else:
                    pending_entry = _PendingEntry(signal, entry_execution)
            if transition.exit_reason is not None:
                if position is None:
                    raise RuntimeError("exact exit intent has no filled position")
                exit_intent = _make_exit_intent(
                    transition.exit_reason, position, observation, parameters
                )
                exit_execution = execute_exit(
                    exit_intent,
                    ordered_windows,
                    market_trading_dates=ordered_dates,
                    settings=config.execution,
                )
                root = memory.accumulation_anchor or before.accumulation_anchor
                if root is None:
                    raise RuntimeError("exit intent lost its immutable root anchor")
                execution_bindings.append(
                    _ExecutionBinding(
                        side="EXIT",
                        signal=position.signal,
                        root_anchor=root,
                        rolling_base=_rolling_base(record, observation),
                        execution=exit_execution,
                        intent=exit_intent,
                    )
                )
                pending_exit = _PendingExit(exit_intent, exit_execution)

        decisions.append(
            _decision_record(
                record=record,
                observation=observation,
                config=config,
                parameters=parameters,
                provenance=provenance,
                memory_before=before,
                memory_after=memory,
                transition=transition,
                trading_index=trading_index,
                phase=phase,
                signal=signal,
                entry_execution=entry_execution,
                actual_entry=actual_entry,
                exit_intent=exit_intent,
                actual_exit=actual_exit,
                lifecycle_termination_reason=lifecycle_termination_reason,
                position_open=position is not None,
                anchor_retention_resolver=anchor_retention_resolver,
            )
        )
        if observation.tradable:
            trading_index += 1
        previous_close = _optional_float(record.get("close"))

    execution_rows = tuple(
        row
        for binding in execution_bindings
        for row in _execution_records(
            binding,
            windows=ordered_windows,
            config=config,
            parameters=parameters,
            provenance=provenance,
        )
    )
    return LifecycleLedgerReplay(
        provenance=provenance,
        parameter_id=parameters.parameter_id,
        decisions=tuple(decisions),
        execution_attempts=execution_rows,
    )


def merge_lifecycle_ledger_replays(
    replays: Sequence[LifecycleLedgerReplay],
) -> LifecycleLedgerReplay:
    """Merge independently replayed symbols in the canonical artifact order."""

    if not replays:
        raise ValueError("at least one lifecycle ledger replay is required")
    first = replays[0]
    if any(item.provenance != first.provenance for item in replays[1:]):
        raise ValueError("cannot merge lifecycle ledgers with different provenance")
    if any(item.parameter_id != first.parameter_id for item in replays[1:]):
        raise ValueError("cannot merge lifecycle ledgers with different parameters")
    decisions = tuple(
        sorted(
            (row for item in replays for row in item.decisions),
            key=lambda row: (
                str(row["symbol"]),
                str(row["decision_at"]),
                str(row["parameter_id"]),
            ),
        )
    )
    executions = tuple(
        sorted(
            (row for item in replays for row in item.execution_attempts),
            key=lambda row: (
                str(row["symbol"]),
                str(row["decision_at"]),
                str(row["side"]),
                int(row["attempt_ordinal"]),
            ),
        )
    )
    return LifecycleLedgerReplay(
        provenance=first.provenance,
        parameter_id=first.parameter_id,
        decisions=decisions,
        execution_attempts=executions,
    )


def write_lifecycle_ledger_artifact(
    path: Path, replay: LifecycleLedgerReplay
) -> LifecycleLedgerArtifact:
    """Create an immutable sibling artifact, or verify an identical prior write."""

    target = path.resolve()
    decision_bytes = _jsonl_bytes(replay.decisions)
    execution_bytes = _jsonl_bytes(replay.execution_attempts)
    manifest = {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "classification": "POST_HOC_REPLAY_ARTIFACT",
        "append_only": True,
        "chip_shard_schema_changed": False,
        "rolling_base_v3_semantics_changed": False,
        "production_strategy_semantics_changed": False,
        "parameter_id": replay.parameter_id,
        "canonical_digest": replay.canonical_digest,
        "provenance": replay.provenance.canonical(),
        "tables": {
            "decisions": {
                "path": DECISION_TABLE,
                "rows": len(replay.decisions),
                "bytes": len(decision_bytes),
                "sha256": hashlib.sha256(decision_bytes).hexdigest(),
            },
            "execution_attempts": {
                "path": EXECUTION_TABLE,
                "rows": len(replay.execution_attempts),
                "bytes": len(execution_bytes),
                "sha256": hashlib.sha256(execution_bytes).hexdigest(),
            },
        },
    }
    manifest_bytes = (_canonical(manifest) + "\n").encode("utf-8")
    expected = {
        DECISION_TABLE: decision_bytes,
        EXECUTION_TABLE: execution_bytes,
        MANIFEST_FILE: manifest_bytes,
    }
    if target.exists():
        if not target.is_dir() or any(
            not (target / name).is_file() or (target / name).read_bytes() != payload
            for name, payload in expected.items()
        ):
            raise FileExistsError(
                f"lifecycle ledger target exists with different content: {target}"
            )
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_name(f".{target.name}.tmp-{os.getpid()}")
        if temp.exists():
            raise FileExistsError(f"lifecycle ledger temporary path exists: {temp}")
        temp.mkdir()
        try:
            for name, payload in expected.items():
                with (temp / name).open("xb") as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
            temp.rename(target)
        except BaseException:
            for child in temp.iterdir() if temp.exists() else ():
                child.unlink()
            if temp.exists():
                temp.rmdir()
            raise
    return LifecycleLedgerArtifact(
        path=target,
        manifest_path=target / MANIFEST_FILE,
        canonical_digest=replay.canonical_digest,
        decision_rows=len(replay.decisions),
        execution_attempt_rows=len(replay.execution_attempts),
    )


def _decision_record(
    *,
    record: Mapping[str, object],
    observation: LifecycleObservation,
    config: MarkupRetestConfig,
    parameters: StrategyParameters,
    provenance: LifecycleLedgerProvenance,
    memory_before: LifecycleMemory,
    memory_after: LifecycleMemory,
    transition: TransitionResult | None,
    trading_index: int,
    phase: str | None,
    signal: StrategySignal | None,
    entry_execution: EntryExecution | None,
    actual_entry: bool,
    exit_intent: ExitIntent | None,
    actual_exit: ExitExecution | None,
    lifecycle_termination_reason: str | None,
    position_open: bool,
    anchor_retention_resolver: AnchorRetentionResolver | None,
) -> dict[str, Any]:
    gates, quantities, retest_evaluated, exit_reason = _decision_gates(
        record=record,
        observation=observation,
        config=config,
        parameters=parameters,
        memory_before=memory_before,
        memory_after=memory_after,
        transition=transition,
        trading_index=trading_index,
        phase=phase,
        position_open=position_open,
        resolver=anchor_retention_resolver,
    )
    failed = [str(gate["name"]) for gate in gates if not gate["passed"]]
    root = memory_before.accumulation_anchor or memory_after.accumulation_anchor
    working = memory_after.working_anchor or memory_before.working_anchor
    active_signal_id = (
        signal.signal_id
        if signal is not None
        else memory_after.active_signal_id or memory_before.active_signal_id
    )
    entry_intent = bool(
        entry_execution is not None
        and entry_execution.status != EntryExecutionStatus.BLOCKED_SIGNAL
    )
    events: list[str] = []
    if (
        memory_before.state in {ChipLifecycleState.NEUTRAL, ChipLifecycleState.BROKEN}
        and observation.setup_score < parameters.setup_score_min
    ):
        events.append("NO_SETUP")
    if observation.setup_score >= parameters.setup_score_min:
        events.append("SETUP_OBSERVED")
    if memory_before.accumulation_anchor is None and memory_after.accumulation_anchor:
        events.append("ROOT_ANCHOR_BOUND")
    if (
        memory_before.state == ChipLifecycleState.ACCUMULATING
        and memory_after.state == ChipLifecycleState.BREAKOUT
    ):
        events.append("BREAKOUT_OBSERVED")
    if retest_evaluated:
        events.append("RETEST_OBSERVED")
    if failed:
        events.append("GATE_FAIL")
    elif gates:
        events.append("GATE_PASS")
    if retest_evaluated and signal is None:
        events.append("REJECTION")
    if signal is not None:
        events.append("QUALIFICATION")
    if entry_intent:
        events.append("ENTRY_INTENT")
    if entry_execution is not None:
        events.append("ENTRY_EXECUTION_ATTEMPT")
    if actual_entry:
        events.append("ACTUAL_ENTRY")
    if exit_intent is not None:
        events.extend(("EXIT_INTENT", "EXIT_EXECUTION_ATTEMPT"))
    if actual_exit is not None:
        events.append("ACTUAL_EXIT")
    root_dropped = (
        memory_before.accumulation_anchor is not None and memory_after.accumulation_anchor is None
    )
    if lifecycle_termination_reason or root_dropped:
        events.append("LIFECYCLE_TERMINATION")
    termination_reason = lifecycle_termination_reason or exit_reason
    payload: dict[str, Any] = {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "symbol": observation.symbol,
        "decision_at": observation.decision_at.isoformat(),
        "available_at": observation.available_at.isoformat(),
        "pit_cutoff": observation.decision_at.isoformat(),
        "parameter_id": parameters.parameter_id,
        "strategy_version": config.strategy_version,
        "signal_id": active_signal_id,
        "lifecycle_id": root.anchor_id if root else None,
        "provenance": provenance.for_symbol(observation.symbol),
        "snapshot_ids": list(observation.snapshot_ids),
        "lifecycle_state_before": memory_before.state.value,
        "lifecycle_state_after": memory_after.state.value,
        "events": list(dict.fromkeys(events)),
        "phase": phase,
        "first_failed_gate": failed[0] if failed else None,
        "all_failed_gates": failed,
        "gates": gates,
        "thresholds_used": _thresholds(config, parameters),
        "qualified_signal": signal is not None,
        "formal_order_authorized": signal.order_authorized if signal else False,
        "entry_intent": entry_intent,
        "entry_execution_status": (
            entry_execution.status.value if entry_execution is not None else None
        ),
        "actual_legal_entry": actual_entry,
        "exit_intent_id": exit_intent.intent_id if exit_intent else None,
        "exit_reason": exit_intent.reason.value if exit_intent else exit_reason,
        "actual_legal_exit": actual_exit is not None,
        "lifecycle_terminated": "LIFECYCLE_TERMINATION" in events,
        "lifecycle_termination_reason": termination_reason,
        "immutable_root_anchor": _anchor(root),
        "working_anchor": _anchor(working),
        "rolling_base_visible_at_decision": _rolling_base(record, observation),
        "quantities": quantities,
        "hard_valid": observation.hard_valid,
        "pit_grade": observation.pit_grade,
        "tradable": observation.tradable,
        "trading_index": trading_index,
    }
    payload["decision_record_id"] = _digest(payload)
    return payload


def _decision_gates(
    *,
    record: Mapping[str, object],
    observation: LifecycleObservation,
    config: MarkupRetestConfig,
    parameters: StrategyParameters,
    memory_before: LifecycleMemory,
    memory_after: LifecycleMemory,
    transition: TransitionResult | None,
    trading_index: int,
    phase: str | None,
    position_open: bool,
    resolver: AnchorRetentionResolver | None,
) -> tuple[list[dict[str, Any]], dict[str, Any], bool, str | None]:
    gates: list[dict[str, Any]] = []

    def gate(
        name: str,
        passed: bool,
        value: Any,
        operator: str,
        threshold: Any,
    ) -> None:
        gates.append(
            {
                "name": name,
                "passed": bool(passed),
                "value": value,
                "operator": operator,
                "threshold": threshold,
            }
        )

    gate(
        "available_at_pit_cutoff",
        observation.available_at <= observation.decision_at,
        observation.available_at.isoformat(),
        "<=",
        observation.decision_at.isoformat(),
    )
    quantities: dict[str, Any] = {
        "accumulation_score": observation.setup_score,
        "accumulation_evidence": {field: bool(record.get(field)) for field, _ in _SETUP_EVIDENCE},
        "breakout_excess_atr": observation.breakout_excess_atr,
        "frozen_support": _frozen(memory_before, memory_after, "breakout_support"),
        "frozen_atr": _frozen(memory_before, memory_after, "breakout_atr"),
        "breakout_volume": _frozen(memory_before, memory_after, "breakout_volume"),
        "breakout_turnover": _frozen(memory_before, memory_after, "breakout_turnover"),
        "pre_breakout_average_cost": _frozen(
            memory_before, memory_after, "pre_breakout_average_cost"
        ),
        "pre_breakout_cost_p50": _frozen(memory_before, memory_after, "pre_breakout_cost_p50"),
        "retest_depth_atr": None,
        "cost_migration_atr": None,
        "retest_volume_ratio": None,
        "retest_turnover_ratio": None,
        "exact_root_retention": None,
        "chip_model_disagreement_atr": observation.chip_model_disagreement_atr,
        "distribution_score_without_root": observation.distribution_score,
        "distribution_score_with_root": None,
        "distribution_evidence": {
            field: bool(record.get(field)) for field, _ in _DISTRIBUTION_EVIDENCE
        },
        "holding_days_before": memory_before.holding_days,
        "holding_days_after": memory_after.holding_days,
        "distribution_days_before": memory_before.distribution_days,
        "distribution_days_after": memory_after.distribution_days,
    }
    if phase is not None:
        if phase in {"ENTRY_PENDING", "EXIT_PENDING"}:
            gate(
                "actual_legal_execution",
                False,
                phase,
                "==",
                "FILLED_NEXT_LEGAL_WINDOW",
            )
        elif phase == "ENTRY_EXECUTION_FAILED":
            gate(
                "entry_execution_completed_legally",
                False,
                phase,
                "==",
                "FILLED",
            )
        elif phase == "ENTRY_CANCELLED_INVALID":
            gate("entry_signal_remains_valid", False, False, "==", True)
        elif phase == "EXIT_FILLED":
            gate("actual_legal_exit", True, True, "==", True)
        return gates, quantities, False, None

    gate(
        "corporate_action_clear",
        not observation.corporate_action_blocking,
        observation.corporate_action_blocking,
        "==",
        False,
    )
    gate("hard_valid", observation.hard_valid, observation.hard_valid, "==", True)
    gate(
        "peak_identity_valid",
        observation.peak_identity_valid,
        observation.peak_identity_valid,
        "==",
        True,
    )
    if (
        observation.corporate_action_blocking
        or not observation.hard_valid
        or not observation.peak_identity_valid
    ):
        reason = (
            ExitReason.CORPORATE_ACTION.value
            if observation.corporate_action_blocking and position_open
            else ExitReason.DATA_INVALID.value
            if position_open
            else None
        )
        return gates, quantities, False, reason
    gate("tradable", observation.tradable, observation.tradable, "==", True)
    if not observation.tradable:
        return gates, quantities, False, None
    if memory_before.cooldown_remaining > 0:
        gate(
            "cooldown_complete",
            False,
            memory_before.cooldown_remaining,
            "==",
            0,
        )
        return gates, quantities, False, None

    if memory_before.state in {
        ChipLifecycleState.NEUTRAL,
        ChipLifecycleState.BROKEN,
    }:
        gate(
            "setup_score",
            observation.setup_score >= parameters.setup_score_min,
            observation.setup_score,
            ">=",
            parameters.setup_score_min,
        )
        return gates, quantities, False, None

    if memory_before.state == ChipLifecycleState.ACCUMULATING:
        if memory_before.accumulation_index is None:
            raise ValueError("ACCUMULATING ledger state is missing accumulation_index")
        elapsed = trading_index - memory_before.accumulation_index
        maximum = config.windows.accumulation * 3
        gate("accumulation_not_expired", elapsed <= maximum, elapsed, "<=", maximum)
        if elapsed > maximum:
            return gates, quantities, False, "ACCUMULATION_EXPIRED"
        gate(
            "breakout_excess_atr",
            observation.breakout_excess_atr >= parameters.breakout_buffer_atr,
            observation.breakout_excess_atr,
            ">=",
            parameters.breakout_buffer_atr,
        )
        return gates, quantities, False, None

    root = memory_before.accumulation_anchor
    if root is None:
        return gates, quantities, False, "MISSING_IMMUTABLE_ROOT"
    estimate = exact_anchor_retention(root, observation, resolver=resolver)
    if estimate is not None:
        quantities["exact_root_retention"] = {
            "central": estimate.central,
            "lower": estimate.lower,
            "upper": estimate.upper,
            "confidence": estimate.confidence,
            "models": [
                {"model": model.value, "retention": value}
                for model, value in estimate.model_retentions
            ],
        }

    if memory_before.active_signal_id is not None:
        gate(
            "exact_root_retention_available",
            estimate is not None,
            estimate is not None,
            "==",
            True,
        )
        if estimate is None:
            return gates, quantities, False, ExitReason.DATA_INVALID.value
        structure_ok = not chip_structure_broken(
            root,
            observation,
            config.fixed,
            comparison_anchor=memory_before.comparison_anchor,
            resolver=resolver,
        )
        gate("root_anchor_structure_continuity", structure_ok, structure_ok, "==", True)
        if not structure_ok:
            return gates, quantities, False, ExitReason.STRUCTURE_BROKEN.value
        support = memory_before.breakout_support
        if support is None:
            raise ValueError("open ledger state is missing frozen breakout support")
        stop_level = support - parameters.protective_stop_atr * observation.atr
        gate(
            "protective_stop_not_hit",
            observation.close >= stop_level,
            observation.close,
            ">=",
            stop_level,
        )
        if observation.close < stop_level:
            return gates, quantities, False, ExitReason.PROTECTIVE_STOP.value
        holding_days = memory_before.holding_days + 1
        gate(
            "maximum_holding_not_reached",
            holding_days < config.windows.max_holding,
            holding_days,
            "<",
            config.windows.max_holding,
        )
        if holding_days >= config.windows.max_holding:
            return gates, quantities, False, ExitReason.MAX_HOLDING_PERIOD.value
        distribution = distribution_score_with_anchor(
            root, observation, config.fixed, resolver=resolver
        )
        quantities["distribution_score_with_root"] = distribution
        distributing = distribution >= parameters.distribution_score_min
        gate(
            "distribution_condition",
            distributing,
            distribution,
            ">=",
            parameters.distribution_score_min,
        )
        confirmation_days = memory_before.distribution_days + 1 if distributing else 0
        gate(
            "consecutive_distribution_confirmation",
            confirmation_days >= config.windows.exit_confirmation,
            confirmation_days,
            ">=",
            config.windows.exit_confirmation,
        )
        reason = (
            ExitReason.DISTRIBUTION_CONFIRMED.value
            if confirmation_days >= config.windows.exit_confirmation
            else None
        )
        return gates, quantities, False, reason

    if memory_before.state != ChipLifecycleState.BREAKOUT:
        return gates, quantities, False, None
    if memory_before.breakout_index is None:
        raise ValueError("BREAKOUT ledger state is missing breakout_index")
    if memory_before.breakout_support is None:
        raise ValueError("BREAKOUT ledger state is missing frozen support")
    price_structure_ok = observation.close >= (
        memory_before.breakout_support - 1.5 * observation.atr
    )
    gate(
        "breakout_price_structure_continuity",
        price_structure_ok,
        observation.close,
        ">=",
        memory_before.breakout_support - 1.5 * observation.atr,
    )
    structure_ok = not chip_structure_broken(
        root,
        observation,
        config.fixed,
        comparison_anchor=memory_before.comparison_anchor,
        resolver=resolver,
    )
    gate("root_anchor_structure_continuity", structure_ok, structure_ok, "==", True)
    if not price_structure_ok or not structure_ok:
        return gates, quantities, False, ExitReason.STRUCTURE_BROKEN.value
    elapsed = trading_index - memory_before.breakout_index
    gate(
        "retest_window_not_expired",
        elapsed <= config.windows.retest_max,
        elapsed,
        "<=",
        config.windows.retest_max,
    )
    if elapsed > config.windows.retest_max:
        return gates, quantities, False, "RETEST_WINDOW_EXPIRED"
    gate(
        "retest_minimum_wait",
        elapsed >= config.windows.retest_min,
        elapsed,
        ">=",
        config.windows.retest_min,
    )
    if elapsed < config.windows.retest_min:
        return gates, quantities, False, None

    required = (
        memory_before.breakout_atr,
        memory_before.breakout_volume,
        memory_before.breakout_turnover,
        memory_before.pre_breakout_average_cost,
        memory_before.pre_breakout_cost_p50,
    )
    if any(value is None for value in required):
        raise ValueError("BREAKOUT ledger state is missing causal retest anchors")
    frozen_atr = cast(float, memory_before.breakout_atr)
    volume = max(cast(float, memory_before.breakout_volume), 1e-12)
    turnover = max(cast(float, memory_before.breakout_turnover), 1e-12)
    depth = abs(memory_before.breakout_support - observation.low) / frozen_atr
    volume_ratio = observation.volume / volume
    turnover_ratio = observation.turnover / turnover
    migration = (
        min(
            observation.average_cost - cast(float, memory_before.pre_breakout_average_cost),
            observation.cost_p50 - cast(float, memory_before.pre_breakout_cost_p50),
        )
        / frozen_atr
    )
    quantities.update(
        {
            "retest_depth_atr": depth,
            "cost_migration_atr": migration,
            "retest_volume_ratio": volume_ratio,
            "retest_turnover_ratio": turnover_ratio,
        }
    )
    same_peak = observation.peak_track_id == root.peak_track_id
    gate(
        "immutable_root_peak_track", same_peak, observation.peak_track_id, "==", root.peak_track_id
    )
    gate(
        "exact_root_retention_available",
        estimate is not None,
        estimate is not None,
        "==",
        True,
    )
    if not same_peak or estimate is None:
        return gates, quantities, True, None
    gate(
        "retest_depth_atr",
        depth <= parameters.max_retest_depth_atr,
        depth,
        "<=",
        parameters.max_retest_depth_atr,
    )
    gate(
        "cost_migration_atr",
        migration >= parameters.min_cost_migration_atr,
        migration,
        ">=",
        parameters.min_cost_migration_atr,
    )
    gate(
        "retest_volume_ratio",
        volume_ratio <= config.fixed.retest_volume_ratio_max,
        volume_ratio,
        "<=",
        config.fixed.retest_volume_ratio_max,
    )
    gate(
        "retest_turnover_ratio",
        turnover_ratio <= config.fixed.retest_turnover_ratio_max,
        turnover_ratio,
        "<=",
        config.fixed.retest_turnover_ratio_max,
    )
    support_regained = (
        observation.close
        >= memory_before.breakout_support - config.fixed.support_tolerance_atr * observation.atr
        and observation.close_vs_vwap >= 0
    )
    gate("frozen_support_regained", support_regained, support_regained, "==", True)
    gate(
        "downside_absorption",
        observation.downside_absorption,
        observation.downside_absorption,
        "==",
        True,
    )
    gate(
        "exact_root_retention_floor",
        estimate.lower >= config.fixed.anchor_retention_floor,
        estimate.lower,
        ">=",
        config.fixed.anchor_retention_floor,
    )
    gate(
        "seller_model_disagreement_atr",
        observation.chip_model_disagreement_atr <= config.fixed.max_model_disagreement_atr,
        observation.chip_model_disagreement_atr,
        "<=",
        config.fixed.max_model_disagreement_atr,
    )
    gate(
        "market_regime",
        observation.market_state in {"RISK_ON", "NEUTRAL"},
        observation.market_state,
        "IN",
        ["NEUTRAL", "RISK_ON"],
    )
    gate(
        "sector_regime",
        observation.sector_state in {"STRONG", "NEUTRAL"},
        observation.sector_state,
        "IN",
        ["NEUTRAL", "STRONG"],
    )
    return gates, quantities, True, None


def _execution_records(
    binding: _ExecutionBinding,
    *,
    windows: Sequence[ExecutionWindow],
    config: MarkupRetestConfig,
    parameters: StrategyParameters,
    provenance: LifecycleLedgerProvenance,
) -> tuple[dict[str, Any], ...]:
    execution = binding.execution
    attempts = execution.attempts
    rows: list[dict[str, Any]] = []
    for ordinal, attempt in enumerate(attempts, start=1):
        window = _attempt_window(binding.signal.symbol, attempt, windows)
        fill_reason = (
            ExecutionReason.FILLED_NEXT_LEGAL_WINDOW.value
            if binding.side == "ENTRY"
            else ExecutionReason.FILLED_NEXT_LEGAL_EXIT_WINDOW.value
        )
        legal = fill_reason in attempt.reason_codes
        failed = [reason for reason in attempt.reason_codes if reason != fill_reason]
        if isinstance(execution, EntryExecution):
            decision_at = execution.signal_decision_at
            available_at = binding.signal.available_at
            status = execution.status.value
            fill_at = execution.fill_at
            fill_price = execution.fill_price
            quantity = execution.quantity
            gross_notional = execution.gross_notional
            commission = execution.commission
            cash_effect = -execution.total_cash if legal else 0.0
            intent_id = binding.signal.signal_id
        else:
            intent = cast(ExitIntent, binding.intent)
            decision_at = execution.intent_decision_at
            available_at = intent.available_at
            status = execution.status.value
            fill_at = execution.fill_at
            fill_price = execution.fill_price
            quantity = execution.quantity
            gross_notional = execution.gross_notional
            commission = execution.commission
            cash_effect = execution.net_proceeds if legal else 0.0
            intent_id = intent.intent_id
        payload: dict[str, Any] = {
            "schema_version": LEDGER_SCHEMA_VERSION,
            "symbol": binding.signal.symbol,
            "decision_at": decision_at.isoformat(),
            "available_at": available_at.isoformat(),
            "pit_cutoff": decision_at.isoformat(),
            "parameter_id": parameters.parameter_id,
            "strategy_version": config.strategy_version,
            "signal_id": binding.signal.signal_id,
            "lifecycle_id": binding.root_anchor.anchor_id,
            "intent_id": intent_id,
            "provenance": provenance.for_symbol(binding.signal.symbol),
            "side": binding.side,
            "attempt_ordinal": ordinal,
            "attempt_trade_date": attempt.trade_date.isoformat(),
            "attempt_window_index": attempt.window_index,
            "attempted_at": attempt.attempted_at.isoformat() if attempt.attempted_at else None,
            "execution_snapshot_id": attempt.snapshot_id,
            "execution_status": status,
            "event": (
                "ACTUAL_ENTRY"
                if legal and binding.side == "ENTRY"
                else "ACTUAL_EXIT"
                if legal
                else "EXECUTION_ATTEMPT"
            ),
            "actual_legal_execution": legal,
            "first_failed_gate": failed[0] if failed else None,
            "all_failed_gates": failed,
            "reason_codes": list(attempt.reason_codes),
            "pass_fail_values": _window_values(window),
            "thresholds_used": {
                "next_window_end": config.execution.next_window_end.isoformat(),
                "max_entry_wait_trading_days": config.execution.max_entry_wait_trading_days,
                "fee_bps": config.execution.fee_bps,
                "slippage_bps": config.execution.slippage_bps,
                "impact_bps": config.execution.impact_bps,
                "board_lot": 100,
                "same_day_fill_allowed": False,
            },
            "fill_at": fill_at.isoformat() if legal and fill_at else None,
            "fill_price": fill_price if legal else None,
            "quantity": quantity if legal else 0,
            "gross_notional": gross_notional if legal else 0.0,
            "commission": commission if legal else 0.0,
            "cash_effect": cash_effect,
            "immutable_root_anchor": _anchor(binding.root_anchor),
            "rolling_base_visible_at_intent": binding.rolling_base,
        }
        payload["execution_record_id"] = _digest(payload)
        rows.append(payload)
    return tuple(rows)


def _make_exit_intent(
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
        intent_id=hashlib.sha256(identity.encode()).hexdigest(),
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


def _apply_position_action(
    position: _Position, observation: LifecycleObservation, trade_date: date
) -> None:
    entry_at = _required_datetime(position.entry.fill_at, "entry fill_at")
    if trade_date <= entry_at.date():
        return
    if observation.share_multiplier == 1.0 and observation.cash_per_share == 0.0:
        return
    position.quantity = round(position.quantity * observation.share_multiplier)


def _replace_exit_binding(
    bindings: list[_ExecutionBinding], intent_id: str, execution: ExitExecution
) -> None:
    matches = [
        item for item in bindings if item.intent is not None and item.intent.intent_id == intent_id
    ]
    if len(matches) != 1:
        raise RuntimeError("exit execution binding is missing or duplicated")
    matches[0].execution = execution


def _attempt_window(
    symbol: str,
    attempt: ExecutionAttempt,
    windows: Sequence[ExecutionWindow],
) -> ExecutionWindow | None:
    if attempt.window_index is None or attempt.snapshot_id is None:
        return None
    matches = tuple(
        window
        for window in windows
        if window.symbol == symbol
        and window.trade_date == attempt.trade_date
        and window.window_index == attempt.window_index
        and window.snapshot_id == attempt.snapshot_id
    )
    if len(matches) > 1:
        return None
    return matches[0] if matches else None


def _window_values(window: ExecutionWindow | None) -> dict[str, Any]:
    if window is None:
        return {
            "window_present": False,
            "hard_valid": None,
            "trade_status": None,
            "market_rule_valid": None,
            "corporate_action_blocking": None,
            "up_limit_price": None,
            "down_limit_price": None,
            "open": None,
            "high": None,
            "low": None,
            "close": None,
            "volume": None,
            "amount": None,
            "vwap": None,
        }
    return {
        "window_present": True,
        "hard_valid": window.hard_valid,
        "trade_status": window.trade_status,
        "market_rule_valid": window.market_rule_valid,
        "corporate_action_blocking": window.corporate_action_blocking,
        "up_limit_price": window.up_limit_price,
        "down_limit_price": window.down_limit_price,
        "open": window.open,
        "high": window.high,
        "low": window.low,
        "close": window.close,
        "volume": window.volume,
        "amount": window.amount,
        "vwap": window.vwap,
    }


def _thresholds(config: MarkupRetestConfig, parameters: StrategyParameters) -> dict[str, Any]:
    return {
        **parameters.canonical(),
        "retest_volume_ratio_max": config.fixed.retest_volume_ratio_max,
        "retest_turnover_ratio_max": config.fixed.retest_turnover_ratio_max,
        "anchor_retention_floor": config.fixed.anchor_retention_floor,
        "anchor_severe_retention_floor": config.fixed.anchor_severe_retention_floor,
        "anchor_band_expansion_ratio_max": config.fixed.anchor_band_expansion_ratio_max,
        "anchor_peak_count_increase_max": config.fixed.anchor_peak_count_increase_max,
        "max_model_disagreement_atr": config.fixed.max_model_disagreement_atr,
        "support_tolerance_atr": config.fixed.support_tolerance_atr,
        "accumulation_expiry_trading_days": config.windows.accumulation * 3,
        "retest_min_trading_days": config.windows.retest_min,
        "retest_max_trading_days": config.windows.retest_max,
        "distribution_confirmation_days": config.windows.exit_confirmation,
        "maximum_holding_days": config.windows.max_holding,
        "cooldown_trading_days": config.windows.cooldown,
    }


def _rolling_base(
    record: Mapping[str, object], observation: LifecycleObservation
) -> dict[str, Any]:
    return {
        "peak_track_id": observation.peak_track_id,
        "peak_track_band_lower": observation.peak_track_band_lower,
        "peak_track_band_upper": observation.peak_track_band_upper,
        "peak_track_ambiguous": observation.peak_track_ambiguous,
        "peak_definition_version": observation.peak_definition_version,
        "peak_track_version": _primitive(record.get("peak_track_version")),
        "peak_track_episode": _primitive(record.get("peak_track_episode")),
        "peak_track_mass": _primitive(record.get("peak_track_mass")),
        "peak_track_prominence": _primitive(record.get("peak_track_prominence")),
        "peak_track_split": _primitive(record.get("peak_track_split")),
        "peak_track_merge": _primitive(record.get("peak_track_merge")),
        "peak_track_lost": _primitive(record.get("peak_track_lost")),
        "prior_peak_track_id": _primitive(record.get("prior_peak_track_id")),
        "state_version": _primitive(record.get("state_version")),
        "feature_config_sha256": _primitive(record.get("feature_config_sha256")),
        "feature_code_sha256": _primitive(record.get("feature_code_sha256")),
    }


def _anchor(anchor: LifecycleAnchor | None) -> dict[str, Any] | None:
    if anchor is None:
        return None
    return {
        "anchor_id": anchor.anchor_id,
        "root_anchor_id": anchor.root_anchor_id,
        "parent_anchor_id": anchor.parent_anchor_id,
        "role": anchor.role,
        "symbol": anchor.symbol,
        "created_at": anchor.created_at.isoformat(),
        "source_snapshot_id": anchor.source_snapshot_id,
        "lower": anchor.lower,
        "upper": anchor.upper,
        "reference_mass": anchor.reference_mass,
        "average_cost": anchor.average_cost,
        "cost_p50": anchor.cost_p50,
        "band_width": anchor.band_width,
        "peak_count": anchor.peak_count,
        "mass_method": anchor.mass_method.value,
        "peak_track_id": anchor.peak_track_id,
    }


def _frozen(before: LifecycleMemory, after: LifecycleMemory, field: str) -> float | None:
    value = getattr(before, field)
    if value is None:
        value = getattr(after, field)
    return cast(float | None, value)


def _primitive(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def _as_date(value: object, *, field: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise TypeError(f"{field} must be a date")


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    return float(cast(Any, value))


def _required_datetime(value: datetime | None, field: str) -> datetime:
    if value is None:
        raise ValueError(f"{field} is required")
    return value


def _jsonl_bytes(rows: Sequence[Mapping[str, Any]]) -> bytes:
    return "".join(_canonical(row) + "\n" for row in rows).encode("utf-8")


def _digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
