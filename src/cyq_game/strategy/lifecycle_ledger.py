"""Deterministic post-hoc lifecycle, decision-gate and execution ledger.

The ledger observes the canonical scalar lifecycle/execution replay.  It does
not define an alternative signal, fill, exit, or chip-state interpretation.
Frozen V3 chip shards are read-only inputs and are referenced by hash.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime
from itertools import groupby
from pathlib import Path
from typing import Any, cast

import duckdb
import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from cyq_game.chip.operator_index import build_operator_symbol_index
from cyq_game.domain import ChipLifecycleState
from cyq_game.strategy.chip_lineage import StreamingLineageSession
from cyq_game.strategy.exact_replay import (
    ExactReplayResult,
    _market_trading_dates,
    _stream_execution_windows,
    evaluate_exact_parameter_lattice_symbol,
)
from cyq_game.strategy.execution import (
    EntryExecution,
    EntryExecutionStatus,
    ExecutionAttempt,
    ExecutionWindow,
    ExitExecution,
    ExitExecutionStatus,
    ExitIntent,
)
from cyq_game.strategy.markup_retest import (
    LifecycleAnchor,
    LifecycleMachine,
    LifecycleMemory,
    LifecycleObservation,
    MarkupRetestConfig,
    StrategyParameters,
    StrategySignal,
    StrategyStage,
    TransitionResult,
    chip_structure_broken,
    distribution_score_with_anchor,
    exact_anchor_retention,
    rebase_lifecycle_memory,
    verify_registered_asset_inventory,
)
from cyq_game.strategy.panel import _create_panel_table, _resolve_corporate_action_inputs
from cyq_game.strategy.semantic_contract import semantic_fingerprint_fields
from cyq_game.strategy.signals import _SIGNAL_INPUT_COLUMNS, stream_panel

LEDGER_SCHEMA_VERSION = "v12-lifecycle-entry-exit-ledger-v1"
EXPECTED_PARAMETER_ID = "9baed76ec299161c"
EXPECTED_ROOT_MANIFEST_SHA256 = "915686c6b9a069688e4790a1e6a8e699feafaf951ca7b720c11ca8b21b85c29a"
EXPECTED_FREEZE_LOCK_SHA256 = "95a7b33ec28fe3c188b309e962522cb1bea16a23b7647c68068864a1e17fd6d9"
EXPECTED_V3_BUILD_COMMIT = "c81bc30a381e8cebcc5b9f8d36524a8a4c9f0151"
EXPECTED_PEAK_TRACK_VERSION = "temporal-chip-peak-v3"
EXPECTED_PEAK_DEFINITION_VERSION = "canonical-chip-peak-v2"
FIVE_SYMBOLS = (
    "000001.SZ",
    "002260.SZ",
    "002706.SZ",
    "300604.SZ",
    "600519.SH",
)
SETUP_COMPONENTS = (
    "ev_turnover_absorption",
    "ev_near_price_chip_growth",
    "ev_concentration_improves",
    "ev_sticky_base",
    "ev_downside_absorption",
)


@dataclass(frozen=True)
class LedgerProvenance:
    frozen_root_manifest_sha256: str
    frozen_lock_sha256: str
    v3_build_commit: str
    ledger_implementation_commit: str
    strategy_parameter_id: str
    strategy_version: str
    semantic_fingerprint: str
    artifact_contract_fingerprint: str
    execution_config_fingerprint: str
    ledger_schema_version: str = LEDGER_SCHEMA_VERSION


@dataclass(frozen=True)
class GateEvaluation:
    phase: str
    name: str
    observed: bool | float | int | str | None
    operator: str
    threshold: bool | float | int | str | None
    passed: bool
    blocking: bool
    source_function: str
    reason_code: str


@dataclass(frozen=True)
class LedgerTables:
    lifecycle_events: tuple[dict[str, Any], ...]
    decision_gates: tuple[dict[str, Any], ...]
    execution_events: tuple[dict[str, Any], ...]
    lifecycle_summary: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class LedgerArtifactResult:
    output_root: Path
    manifest_path: Path
    artifact_hashes: Mapping[str, str]
    row_counts: Mapping[str, int]
    summary_counts: Mapping[str, int]


def accepted_strategy_parameters() -> StrategyParameters:
    parameters = StrategyParameters(
        setup_score_min=1.0,
        breakout_buffer_atr=0.25,
        max_retest_depth_atr=0.50,
        min_cost_migration_atr=0.50,
        distribution_score_min=0.80,
        protective_stop_atr=1.50,
    )
    if parameters.parameter_id != EXPECTED_PARAMETER_ID:
        raise RuntimeError("accepted strategy parameter identity changed")
    return parameters


def deterministic_lifecycle_id(parameter_id: str, anchor: LifecycleAnchor) -> str:
    payload = "|".join(
        (
            LEDGER_SCHEMA_VERSION,
            "LIFECYCLE",
            anchor.symbol,
            parameter_id,
            anchor.root_anchor_id,
            anchor.created_at.isoformat(),
        )
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _stable_id(kind: str, *parts: object) -> str:
    return hashlib.sha256(
        "|".join((LEDGER_SCHEMA_VERSION, kind, *(str(item) for item in parts))).encode()
    ).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_head(worktree: Path) -> str:
    return subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=worktree,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _provenance_columns(provenance: LedgerProvenance) -> dict[str, str]:
    return {
        "frozen_root_manifest_sha256": provenance.frozen_root_manifest_sha256,
        "frozen_lock_sha256": provenance.frozen_lock_sha256,
        "v3_build_commit": provenance.v3_build_commit,
        "ledger_implementation_commit": provenance.ledger_implementation_commit,
        "strategy_parameter_id": provenance.strategy_parameter_id,
        "strategy_version": provenance.strategy_version,
        "semantic_fingerprint": provenance.semantic_fingerprint,
        "artifact_contract_fingerprint": provenance.artifact_contract_fingerprint,
        "execution_config_fingerprint": provenance.execution_config_fingerprint,
        "ledger_schema_version": provenance.ledger_schema_version,
    }


def load_and_validate_freeze(
    *,
    frozen_root: Path,
    freeze_lock_path: Path,
    parameters: StrategyParameters,
) -> tuple[dict[str, Any], dict[str, Any], tuple[str, ...]]:
    root_manifest_path = frozen_root / "manifest.json"
    if _sha256(root_manifest_path) != EXPECTED_ROOT_MANIFEST_SHA256:
        raise ValueError("wrong frozen V3 root manifest")
    if _sha256(freeze_lock_path) != EXPECTED_FREEZE_LOCK_SHA256:
        raise ValueError("wrong frozen V3 freeze lock")
    if parameters.parameter_id != EXPECTED_PARAMETER_ID:
        raise ValueError("wrong accepted strategy parameter ID")
    root_manifest = json.loads(root_manifest_path.read_text(encoding="utf-8"))
    lock = json.loads(freeze_lock_path.read_text(encoding="utf-8"))
    audit = lock.get("final_audit") or {}
    if audit.get("root_manifest_sha256") != EXPECTED_ROOT_MANIFEST_SHA256:
        raise ValueError("freeze lock does not bind the required root manifest")
    if lock.get("peak_track_version") != EXPECTED_PEAK_TRACK_VERSION:
        raise ValueError("freeze lock has the wrong temporal peak track")
    if lock.get("peak_definition_version") != EXPECTED_PEAK_DEFINITION_VERSION:
        raise ValueError("freeze lock has the wrong peak definition")
    if audit.get("symbols") != 500 or audit.get("feature_rows") != 121_251:
        raise ValueError("freeze lock does not describe the governed 500-symbol build")
    symbols = tuple(str(item) for item in lock.get("ordered_symbols") or ())
    if len(symbols) != 500 or len(set(symbols)) != 500:
        raise ValueError("freeze lock ordered universe is incomplete or duplicated")
    return root_manifest, lock, symbols


def verify_frozen_files(frozen_root: Path, lock: Mapping[str, Any]) -> dict[str, Any]:
    """Verify every manifest-bound chip file by size and SHA-256."""

    bindings = cast(
        Mapping[str, str],
        cast(Mapping[str, Any], lock["final_manifest_hash_bindings"])["per_symbol_manifest_sha256"],
    )
    file_count = 1
    byte_count = (frozen_root / "manifest.json").stat().st_size
    logical: list[dict[str, object]] = [
        {
            "path": "manifest.json",
            "bytes": byte_count,
            "sha256": _sha256(frozen_root / "manifest.json"),
        }
    ]
    for symbol in cast(Sequence[str], lock["ordered_symbols"]):
        manifest_path = frozen_root / f"symbol={symbol}" / "manifest.json"
        digest = _sha256(manifest_path)
        if digest != bindings.get(symbol):
            raise ValueError(f"{symbol}: frozen symbol manifest digest mismatch")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        logical.append(
            {
                "path": str(manifest_path.relative_to(frozen_root)),
                "bytes": manifest_path.stat().st_size,
                "sha256": digest,
            }
        )
        file_count += 1
        byte_count += manifest_path.stat().st_size
        for item in manifest["artifact"]["file_metadata"]:
            path = frozen_root / str(item["relative_path"])
            size = path.stat().st_size
            if size != int(item["bytes"]):
                raise ValueError(f"{path}: frozen file size mismatch")
            digest = _sha256(path)
            if digest != item["sha256"]:
                raise ValueError(f"{path}: frozen file digest mismatch")
            logical.append(
                {
                    "path": str(item["relative_path"]),
                    "bytes": size,
                    "sha256": digest,
                }
            )
            file_count += 1
            byte_count += size
    return {
        "files": file_count,
        "bytes": byte_count,
        "tree_sha256": hashlib.sha256(_canonical_json(logical).encode()).hexdigest(),
    }


def _gate(
    phase: str,
    name: str,
    observed: bool | float | int | str | None,
    operator: str,
    threshold: bool | float | int | str | None,
    passed: bool,
    *,
    source: str,
    reason: str,
    blocking: bool = True,
) -> GateEvaluation:
    return GateEvaluation(
        phase=phase,
        name=name,
        observed=observed,
        operator=operator,
        threshold=threshold,
        passed=passed,
        blocking=blocking,
        source_function=source,
        reason_code=reason,
    )


def _state(value: LifecycleMemory) -> str:
    return value.state.value


def _retention(
    machine: LifecycleMachine,
    memory: LifecycleMemory,
    observation: LifecycleObservation,
) -> Any | None:
    anchor = memory.accumulation_anchor
    if anchor is None:
        return None
    return exact_anchor_retention(
        anchor,
        observation,
        resolver=machine.anchor_retention_resolver,
    )


def evaluate_decision_gates(
    machine: LifecycleMachine,
    memory_before: LifecycleMemory,
    observation: LifecycleObservation,
    *,
    trading_index: int,
    record: Mapping[str, object],
) -> tuple[GateEvaluation, ...]:
    """Expose exact operands in the same phase/order as ``LifecycleMachine``.

    The production transition remains authoritative.  This function only
    records the already-defined operands and thresholds; it never supplies a
    transition result to replay.
    """

    gates: list[GateEvaluation] = []

    def add(
        phase: str,
        name: str,
        observed: bool | float | int | str | None,
        operator: str,
        threshold: bool | float | int | str | None,
        passed: bool,
        source: str,
        reason: str,
        *,
        blocking: bool = True,
    ) -> None:
        gates.append(
            _gate(
                phase,
                name,
                observed,
                operator,
                threshold,
                passed,
                source=source,
                reason=reason,
                blocking=blocking,
            )
        )

    active = memory_before.active_signal_id is not None
    phase = "EXIT" if active else "VALIDITY"
    add(
        phase,
        "corporate_action_clear",
        observation.corporate_action_blocking,
        "==",
        False,
        not observation.corporate_action_blocking,
        "LifecycleMachine.advance/_advance_open",
        "CORPORATE_ACTION_BLOCK",
    )
    add(
        phase,
        "hard_valid",
        observation.hard_valid,
        "==",
        True,
        observation.hard_valid,
        "LifecycleMachine.advance/_advance_open",
        "DATA_INVALID",
    )
    add(
        phase,
        "peak_identity_valid",
        observation.peak_identity_valid,
        "==",
        True,
        observation.peak_identity_valid,
        "LifecycleObservation.peak_identity_valid",
        "PEAK_IDENTITY_INVALID",
    )
    if (
        observation.corporate_action_blocking
        or not observation.hard_valid
        or not observation.peak_identity_valid
    ):
        return tuple(gates)

    memory = rebase_lifecycle_memory(memory_before, observation)
    if active:
        add(
            "EXIT",
            "tradable",
            observation.tradable,
            "==",
            True,
            observation.tradable,
            "LifecycleMachine._advance_open",
            "SUSPENDED_OR_NOT_TRADABLE",
        )
        if not observation.tradable or memory.pending_exit_reason is not None:
            return tuple(gates)
        estimate = _retention(machine, memory, observation)
        add(
            "EXIT",
            "exact_root_retention_available",
            estimate is not None,
            "==",
            True,
            estimate is not None,
            "exact_anchor_retention",
            "EXACT_ROOT_LINEAGE_UNAVAILABLE",
        )
        if estimate is None or memory.accumulation_anchor is None:
            return tuple(gates)
        broken = chip_structure_broken(
            memory.accumulation_anchor,
            observation,
            machine.config.fixed,
            comparison_anchor=memory.comparison_anchor,
            resolver=machine.anchor_retention_resolver,
        )
        add(
            "EXIT",
            "root_structure_intact",
            broken,
            "==",
            False,
            not broken,
            "chip_structure_broken",
            "STRUCTURE_BROKEN",
        )
        support = memory.breakout_support or observation.structure_support
        stop = support - machine.parameters.protective_stop_atr * observation.atr
        add(
            "EXIT",
            "protective_stop_intact",
            observation.close,
            ">=",
            stop,
            observation.close >= stop,
            "LifecycleMachine._advance_open",
            "PROTECTIVE_STOP",
        )
        holding_days = memory.holding_days + 1
        add(
            "EXIT",
            "below_max_holding",
            holding_days,
            "<",
            machine.config.windows.max_holding,
            holding_days < machine.config.windows.max_holding,
            "LifecycleMachine._advance_open",
            "MAX_HOLDING_PERIOD",
        )
        score = distribution_score_with_anchor(
            memory.accumulation_anchor,
            observation,
            machine.config.fixed,
            resolver=machine.anchor_retention_resolver,
        )
        distributing = score >= machine.parameters.distribution_score_min
        add(
            "EXIT",
            "distribution_below_threshold",
            score,
            "<",
            machine.parameters.distribution_score_min,
            not distributing,
            "distribution_score_with_anchor",
            "DISTRIBUTION_EVIDENCE",
            blocking=False,
        )
        distribution_days = memory.distribution_days + 1 if distributing else 0
        add(
            "EXIT",
            "distribution_not_confirmed",
            distribution_days,
            "<",
            machine.config.windows.exit_confirmation,
            distribution_days < machine.config.windows.exit_confirmation,
            "LifecycleMachine._advance_open",
            "DISTRIBUTION_CONFIRMED",
        )
        return tuple(gates)

    add(
        "LIFECYCLE",
        "tradable",
        observation.tradable,
        "==",
        True,
        observation.tradable,
        "LifecycleMachine.advance",
        "SUSPENDED_OR_NOT_TRADABLE",
    )
    if not observation.tradable:
        return tuple(gates)
    if memory.cooldown_remaining > 0:
        add(
            "LIFECYCLE",
            "cooldown_complete",
            memory.cooldown_remaining,
            "==",
            0,
            False,
            "LifecycleMachine.advance",
            "COOLDOWN_ACTIVE",
        )
        return tuple(gates)

    if memory.state in {ChipLifecycleState.NEUTRAL, ChipLifecycleState.BROKEN}:
        for component in SETUP_COMPONENTS:
            observed = bool(record.get(component))
            add(
                "ACCUMULATION",
                component,
                observed,
                "==",
                True,
                observed,
                "panel._create_panel_table",
                f"{component.upper()}_FALSE",
                blocking=False,
            )
        add(
            "ACCUMULATION",
            "setup_score",
            observation.setup_score,
            ">=",
            machine.parameters.setup_score_min,
            observation.setup_score >= machine.parameters.setup_score_min,
            "LifecycleMachine.advance",
            "ACCUMULATION_SCORE_BELOW_THRESHOLD",
        )
        return tuple(gates)

    if memory.state == ChipLifecycleState.ACCUMULATING:
        assert memory.accumulation_index is not None
        elapsed = trading_index - memory.accumulation_index
        expiry = machine.config.windows.accumulation * 3
        add(
            "BREAKOUT",
            "accumulation_not_expired",
            elapsed,
            "<=",
            expiry,
            elapsed <= expiry,
            "LifecycleMachine.advance",
            "ACCUMULATION_EXPIRED",
        )
        add(
            "BREAKOUT",
            "breakout_excess_atr",
            observation.breakout_excess_atr,
            ">=",
            machine.parameters.breakout_buffer_atr,
            observation.breakout_excess_atr >= machine.parameters.breakout_buffer_atr,
            "LifecycleMachine.advance",
            "BREAKOUT_EXCESS_BELOW_THRESHOLD",
        )
        add(
            "BREAKOUT",
            "seller_model_disagreement_atr",
            observation.chip_model_disagreement_atr,
            "<=",
            machine.config.fixed.max_model_disagreement_atr,
            observation.chip_model_disagreement_atr
            <= machine.config.fixed.max_model_disagreement_atr,
            "LifecycleMachine._retest_qualified",
            "MODEL_DISAGREEMENT_ABOVE_THRESHOLD",
            blocking=False,
        )
        return tuple(gates)

    if memory.state != ChipLifecycleState.BREAKOUT:
        return tuple(gates)
    if memory.breakout_index is None or memory.accumulation_anchor is None:
        raise ValueError("BREAKOUT state is missing frozen lifecycle anchors")
    elapsed = trading_index - memory.breakout_index
    price_broken = machine._breakout_price_structure_broken(memory, observation)
    chip_broken = chip_structure_broken(
        memory.accumulation_anchor,
        observation,
        machine.config.fixed,
        comparison_anchor=memory.comparison_anchor,
        resolver=machine.anchor_retention_resolver,
    )
    add(
        "RETEST",
        "breakout_price_structure_intact",
        price_broken,
        "==",
        False,
        not price_broken,
        "LifecycleMachine._breakout_price_structure_broken",
        "BREAKOUT_PRICE_STRUCTURE_BROKEN",
    )
    add(
        "RETEST",
        "root_structure_intact",
        chip_broken,
        "==",
        False,
        not chip_broken,
        "chip_structure_broken",
        "ROOT_STRUCTURE_BROKEN",
    )
    add(
        "RETEST",
        "within_retest_window",
        elapsed,
        "<=",
        machine.config.windows.retest_max,
        elapsed <= machine.config.windows.retest_max,
        "LifecycleMachine.advance",
        "RETEST_WINDOW_EXPIRED",
    )
    add(
        "RETEST",
        "retest_window_started",
        elapsed,
        ">=",
        machine.config.windows.retest_min,
        elapsed >= machine.config.windows.retest_min,
        "LifecycleMachine.advance",
        "RETEST_WINDOW_NOT_STARTED",
    )
    if (
        price_broken
        or chip_broken
        or not (machine.config.windows.retest_min <= elapsed <= machine.config.windows.retest_max)
    ):
        return tuple(gates)

    required = (
        memory.breakout_support,
        memory.breakout_atr,
        memory.breakout_volume,
        memory.breakout_turnover,
        memory.pre_breakout_average_cost,
        memory.pre_breakout_cost_p50,
    )
    if any(item is None for item in required):
        raise ValueError("BREAKOUT state is missing causal retest anchors")
    support = cast(float, memory.breakout_support)
    frozen_atr = cast(float, memory.breakout_atr)
    volume = max(cast(float, memory.breakout_volume), 1e-12)
    turnover = max(cast(float, memory.breakout_turnover), 1e-12)
    depth = abs(support - observation.low) / frozen_atr
    volume_ratio = observation.volume / volume
    turnover_ratio = observation.turnover / turnover
    migration = (
        min(
            observation.average_cost - cast(float, memory.pre_breakout_average_cost),
            observation.cost_p50 - cast(float, memory.pre_breakout_cost_p50),
        )
        / frozen_atr
    )
    estimate = _retention(machine, memory, observation)
    support_regained = machine._breakout_support_regained(memory, observation)
    specs = (
        (
            "retest_depth_atr",
            depth,
            "<=",
            machine.parameters.max_retest_depth_atr,
            depth <= machine.parameters.max_retest_depth_atr,
            "RETEST_DEPTH_ABOVE_THRESHOLD",
        ),
        (
            "cost_migration_atr",
            migration,
            ">=",
            machine.parameters.min_cost_migration_atr,
            migration >= machine.parameters.min_cost_migration_atr,
            "COST_MIGRATION_BELOW_THRESHOLD",
        ),
        (
            "retest_volume_ratio",
            volume_ratio,
            "<=",
            machine.config.fixed.retest_volume_ratio_max,
            volume_ratio <= machine.config.fixed.retest_volume_ratio_max,
            "RETEST_VOLUME_RATIO_ABOVE_THRESHOLD",
        ),
        (
            "retest_turnover_ratio",
            turnover_ratio,
            "<=",
            machine.config.fixed.retest_turnover_ratio_max,
            turnover_ratio <= machine.config.fixed.retest_turnover_ratio_max,
            "RETEST_TURNOVER_RATIO_ABOVE_THRESHOLD",
        ),
        (
            "breakout_support_regained",
            support_regained,
            "==",
            True,
            support_regained,
            "BREAKOUT_SUPPORT_NOT_REGAINED",
        ),
        (
            "downside_absorption",
            observation.downside_absorption,
            "==",
            True,
            observation.downside_absorption,
            "DOWNSIDE_ABSORPTION_FALSE",
        ),
        (
            "exact_root_retention",
            estimate.lower if estimate else None,
            ">=",
            machine.config.fixed.anchor_retention_floor,
            estimate is not None and estimate.lower >= machine.config.fixed.anchor_retention_floor,
            "ROOT_RETENTION_BELOW_THRESHOLD",
        ),
        (
            "seller_model_disagreement_atr",
            observation.chip_model_disagreement_atr,
            "<=",
            machine.config.fixed.max_model_disagreement_atr,
            observation.chip_model_disagreement_atr
            <= machine.config.fixed.max_model_disagreement_atr,
            "MODEL_DISAGREEMENT_ABOVE_THRESHOLD",
        ),
        (
            "market_state",
            observation.market_state,
            "IN",
            "RISK_ON|NEUTRAL",
            observation.market_state in {"RISK_ON", "NEUTRAL"},
            "MARKET_STATE_BLOCKED",
        ),
        (
            "sector_state",
            observation.sector_state,
            "IN",
            "STRONG|NEUTRAL",
            observation.sector_state in {"STRONG", "NEUTRAL"},
            "SECTOR_STATE_BLOCKED",
        ),
    )
    for name, observed, operator, threshold, passed, reason in specs:
        add(
            "RETEST",
            name,
            observed,
            operator,
            threshold,
            passed,
            "LifecycleMachine._retest_qualified",
            reason,
        )
    return tuple(gates)


def _first_failed(gates: Sequence[GateEvaluation]) -> str | None:
    return next(
        (gate.name for gate in gates if gate.blocking and not gate.passed),
        None,
    )


def _failed(gates: Sequence[GateEvaluation]) -> tuple[str, ...]:
    return tuple(gate.name for gate in gates if gate.blocking and not gate.passed)


class LifecycleLedgerCollector:
    """Append-only observer attached to one canonical symbol replay."""

    def __init__(
        self,
        *,
        config: MarkupRetestConfig,
        parameters: StrategyParameters,
        provenance: LedgerProvenance,
        windows: Sequence[ExecutionWindow],
        anchor_retention_resolver: StreamingLineageSession | None,
    ) -> None:
        self.config = config
        self.parameters = parameters
        self.provenance = provenance
        self.machine = LifecycleMachine(
            config,
            parameters,
            anchor_retention_resolver=anchor_retention_resolver,
        )
        self.lifecycle_events: list[dict[str, Any]] = []
        self.decision_gates: list[dict[str, Any]] = []
        self.execution_events: list[dict[str, Any]] = []
        self._windows_by_snapshot = {item.snapshot_id: item for item in windows}
        self._windows_by_key = {(item.trade_date, item.window_index): item for item in windows}

    def _lifecycle(
        self,
        memory_before: LifecycleMemory,
        transition: TransitionResult,
        observation: LifecycleObservation,
    ) -> tuple[str, LifecycleAnchor | None]:
        anchor = memory_before.accumulation_anchor or transition.memory.accumulation_anchor
        if anchor is not None:
            return deterministic_lifecycle_id(self.parameters.parameter_id, anchor), anchor
        candidate = _stable_id(
            "CANDIDATE",
            observation.symbol,
            self.parameters.parameter_id,
            observation.decision_at.isoformat(),
        )
        return candidate, None

    def _base(
        self,
        *,
        lifecycle_id: str,
        symbol: str,
        root_anchor_id: str | None,
        rolling_base_id: str | None,
        signal_id: str | None,
    ) -> dict[str, Any]:
        return {
            "lifecycle_id": lifecycle_id,
            "symbol": symbol,
            "root_anchor_id": root_anchor_id,
            "rolling_structural_base_id": rolling_base_id,
            "signal_id": signal_id,
            **_provenance_columns(self.provenance),
        }

    @staticmethod
    def _assert_pit(available_at: datetime, decision_at: datetime) -> None:
        if available_at > decision_at:
            raise ValueError(
                f"ledger PIT breach: available_at={available_at.isoformat()} "
                f"> decision_at={decision_at.isoformat()}"
            )

    def _event(
        self,
        *,
        base: Mapping[str, Any],
        event_type: str,
        phase: str,
        state_before: str,
        state_after: str,
        decision_at: datetime,
        available_at: datetime,
        reason: str,
        terminal: bool,
        first_failed_gate: str | None,
        failed_gates: Sequence[str],
        snapshot_ids: Sequence[str],
        details: Mapping[str, Any] | None = None,
        event_at: datetime | None = None,
    ) -> None:
        self._assert_pit(available_at, decision_at)
        identity = _stable_id(
            "LIFECYCLE_EVENT",
            base["lifecycle_id"],
            event_type,
            event_at.isoformat() if event_at else decision_at.isoformat(),
            len(self.lifecycle_events),
        )
        self.lifecycle_events.append(
            {
                "event_id": identity,
                **base,
                "event_type": event_type,
                "phase": phase,
                "state_before": state_before,
                "state_after": state_after,
                "decision_at": decision_at.isoformat(),
                "available_at": available_at.isoformat(),
                "event_at": (event_at or decision_at).isoformat(),
                "transition_reason": reason,
                "terminal": terminal,
                "first_failed_gate": first_failed_gate,
                "failed_gates_json": _canonical_json(tuple(failed_gates)),
                "snapshot_ids_json": _canonical_json(tuple(snapshot_ids)),
                "details_json": _canonical_json(details or {}),
            }
        )

    def on_lifecycle_decision(
        self,
        *,
        parameters: StrategyParameters,
        memory_before: LifecycleMemory,
        observation: LifecycleObservation,
        trading_index: int,
        transition: TransitionResult,
        record: Mapping[str, object],
        is_evaluation: bool,
    ) -> None:
        if parameters != self.parameters:
            raise ValueError("ledger collector received a different parameter set")
        self._assert_pit(observation.available_at, observation.decision_at)
        lifecycle_id, anchor = self._lifecycle(memory_before, transition, observation)
        signal_id = (
            transition.signal.signal_id
            if transition.signal is not None
            else memory_before.active_signal_id or transition.memory.active_signal_id
        )
        base = self._base(
            lifecycle_id=lifecycle_id,
            symbol=observation.symbol,
            root_anchor_id=anchor.root_anchor_id if anchor else None,
            rolling_base_id=observation.peak_track_id,
            signal_id=signal_id,
        )
        gates = evaluate_decision_gates(
            self.machine,
            memory_before,
            observation,
            trading_index=trading_index,
            record=record,
        )
        failed = _failed(gates)
        first = _first_failed(gates)
        for order, gate in enumerate(gates):
            value = gate.observed
            threshold = gate.threshold
            self.decision_gates.append(
                {
                    "gate_id": _stable_id(
                        "GATE",
                        lifecycle_id,
                        observation.decision_at.isoformat(),
                        order,
                        gate.name,
                    ),
                    **base,
                    "gate_order": order,
                    "phase": gate.phase,
                    "gate_name": gate.name,
                    "observed_json": _canonical_json(value),
                    "observed_number": (
                        float(value)
                        if isinstance(value, (int, float)) and not isinstance(value, bool)
                        else None
                    ),
                    "observed_bool": value if isinstance(value, bool) else None,
                    "observed_text": value if isinstance(value, str) else None,
                    "operator": gate.operator,
                    "threshold_json": _canonical_json(threshold),
                    "passed": gate.passed,
                    "blocking": gate.blocking,
                    "first_failed": gate.name == first,
                    "source_function": gate.source_function,
                    "reason_code": gate.reason_code,
                    "decision_at": observation.decision_at.isoformat(),
                    "available_at": observation.available_at.isoformat(),
                    "is_evaluation": is_evaluation,
                    "snapshot_ids_json": _canonical_json(observation.snapshot_ids),
                }
            )

        before = _state(memory_before)
        after = _state(transition.memory)
        details = {
            "trading_index": trading_index,
            "setup_score": observation.setup_score,
            "breakout_excess_atr": observation.breakout_excess_atr,
            "frozen_breakout_support": transition.memory.breakout_support,
            "frozen_breakout_atr": transition.memory.breakout_atr,
            "frozen_breakout_volume": transition.memory.breakout_volume,
            "frozen_breakout_turnover": transition.memory.breakout_turnover,
            "pre_breakout_average_cost": transition.memory.pre_breakout_average_cost,
            "pre_breakout_cost_p50": transition.memory.pre_breakout_cost_p50,
            "holding_days": transition.memory.holding_days,
            "distribution_days": transition.memory.distribution_days,
            "is_evaluation": is_evaluation,
        }
        events: list[tuple[str, str]] = []
        if (
            transition.memory.state == ChipLifecycleState.ACCUMULATING
            and memory_before.state != ChipLifecycleState.ACCUMULATING
        ):
            events.extend(
                (("SETUP_OBSERVED", "ACCUMULATION"), ("ROOT_ANCHOR_BOUND", "ACCUMULATION"))
            )
        elif (
            transition.memory.state == ChipLifecycleState.BREAKOUT
            and memory_before.state != ChipLifecycleState.BREAKOUT
        ):
            events.append(("BREAKOUT_OBSERVED", "BREAKOUT"))
        elif transition.signal is not None:
            events.extend((("RETEST_OBSERVED", "RETEST"), ("QUALIFIED", "ENTRY")))
        elif transition.exit_reason is not None:
            events.append(("EXIT_CONDITION", "EXIT"))
        elif before != after:
            events.append(("LIFECYCLE_TRANSITION", "LIFECYCLE"))
        elif first is not None:
            event_phase = gates[-1].phase if gates else "LIFECYCLE"
            events.append((f"{event_phase}_REJECTED", event_phase))
        for event_type, event_phase in events:
            self._event(
                base=base,
                event_type=event_type,
                phase=event_phase,
                state_before=before,
                state_after=after,
                decision_at=observation.decision_at,
                available_at=observation.available_at,
                reason=(
                    transition.exit_reason.value
                    if transition.exit_reason is not None
                    else first or event_type
                ),
                terminal=False,
                first_failed_gate=first,
                failed_gates=failed,
                snapshot_ids=observation.snapshot_ids,
                details=details,
            )

    def _window_for_attempt(self, attempt: ExecutionAttempt) -> ExecutionWindow | None:
        if attempt.snapshot_id is not None:
            result = self._windows_by_snapshot.get(attempt.snapshot_id)
            if result is not None:
                return result
        if attempt.window_index is None:
            return None
        return self._windows_by_key.get((attempt.trade_date, attempt.window_index))

    def _execution_row(
        self,
        *,
        base: Mapping[str, Any],
        execution_id: str,
        intent_id: str,
        side: str,
        event_type: str,
        status: str,
        intent_at: datetime,
        event_at: datetime,
        available_at: datetime,
        attempt: ExecutionAttempt | None,
        window: ExecutionWindow | None,
        reason_codes: Sequence[str],
        fill_price: float | None = None,
        quantity: int = 0,
        gross_notional: float = 0.0,
        commission: float = 0.0,
        cash_value: float = 0.0,
        blocked_tail_loss: float = 0.0,
    ) -> None:
        self._assert_pit(available_at, event_at)
        self.execution_events.append(
            {
                "execution_event_id": _stable_id(
                    "EXECUTION_EVENT",
                    execution_id,
                    event_type,
                    event_at.isoformat(),
                    len(self.execution_events),
                ),
                **base,
                "execution_id": execution_id,
                "intent_id": intent_id,
                "side": side,
                "event_type": event_type,
                "status": status,
                "intent_at": intent_at.isoformat(),
                "decision_at": event_at.isoformat(),
                "available_at": available_at.isoformat(),
                "execution_at": event_at.isoformat() if event_type.endswith("FILLED") else None,
                "trade_date": event_at.date().isoformat(),
                "window_index": attempt.window_index if attempt else None,
                "window_snapshot_id": attempt.snapshot_id if attempt else None,
                "window_open": window.open if window else None,
                "window_high": window.high if window else None,
                "window_low": window.low if window else None,
                "window_close": window.close if window else None,
                "window_vwap": window.vwap if window else None,
                "up_limit_price": window.up_limit_price if window else None,
                "down_limit_price": window.down_limit_price if window else None,
                "trade_status": window.trade_status if window else None,
                "reason_codes_json": _canonical_json(tuple(reason_codes)),
                "fill_price": fill_price,
                "quantity": quantity,
                "gross_notional": gross_notional,
                "commission": commission,
                "cash_value": cash_value,
                "blocked_tail_loss": blocked_tail_loss,
            }
        )

    def on_entry_execution(
        self,
        *,
        parameters: StrategyParameters,
        signal: StrategySignal,
        execution: EntryExecution,
        observation: LifecycleObservation,
    ) -> None:
        anchor = LifecycleAnchor(
            anchor_id=signal.root_anchor_id,
            symbol=signal.symbol,
            source_snapshot_id="|".join(signal.snapshot_ids),
            root_anchor_id=signal.root_anchor_id,
            parent_anchor_id=None,
            role="ROOT",
            created_at=signal.anchor_created_at,
            lower=signal.anchor_lower,
            upper=signal.anchor_upper,
            reference_mass=signal.anchor_reference_mass,
            average_cost=signal.anchor_lower,
            cost_p50=signal.anchor_lower,
            band_width=max(signal.anchor_upper - signal.anchor_lower, 1e-12),
            peak_count=1,
            mass_method=signal.anchor_mass_method,
        )
        lifecycle_id = deterministic_lifecycle_id(parameters.parameter_id, anchor)
        base = self._base(
            lifecycle_id=lifecycle_id,
            symbol=signal.symbol,
            root_anchor_id=signal.root_anchor_id,
            rolling_base_id=observation.peak_track_id,
            signal_id=signal.signal_id,
        )
        execution_id = _stable_id("ENTRY_EXECUTION", signal.signal_id)
        self._execution_row(
            base=base,
            execution_id=execution_id,
            intent_id=signal.signal_id,
            side="ENTRY",
            event_type="ENTRY_INTENT",
            status=execution.status.value,
            intent_at=signal.decision_at,
            event_at=signal.decision_at,
            available_at=signal.available_at,
            attempt=None,
            window=None,
            reason_codes=execution.reason_codes,
        )
        for attempt in execution.attempts:
            window = self._window_for_attempt(attempt)
            attempted_at = attempt.attempted_at or datetime.combine(
                attempt.trade_date,
                self.config.execution.next_window_end,
            )
            self._execution_row(
                base=base,
                execution_id=execution_id,
                intent_id=signal.signal_id,
                side="ENTRY",
                event_type="ENTRY_EXECUTION_ATTEMPT",
                status="REJECTED",
                intent_at=signal.decision_at,
                event_at=attempted_at,
                available_at=attempted_at,
                attempt=attempt,
                window=window,
                reason_codes=attempt.reason_codes,
            )
        terminal_at = execution.fill_at
        if terminal_at is None:
            terminal_at = (
                execution.attempts[-1].attempted_at
                if execution.attempts and execution.attempts[-1].attempted_at is not None
                else signal.decision_at
            )
        fill_window = next(
            (
                window
                for window in self._windows_by_snapshot.values()
                if execution.fill_at is not None and window.available_at == execution.fill_at
            ),
            None,
        )
        self._execution_row(
            base=base,
            execution_id=execution_id,
            intent_id=signal.signal_id,
            side="ENTRY",
            event_type=(
                "ENTRY_FILLED"
                if execution.status == EntryExecutionStatus.FILLED
                else "ENTRY_DEFERRED_OR_FAILED"
            ),
            status=execution.status.value,
            intent_at=signal.decision_at,
            event_at=terminal_at,
            available_at=terminal_at,
            attempt=None,
            window=fill_window,
            reason_codes=execution.reason_codes,
            fill_price=execution.fill_price,
            quantity=execution.quantity,
            gross_notional=execution.gross_notional,
            commission=execution.commission,
            cash_value=execution.total_cash,
        )

    def on_exit_execution(
        self,
        *,
        parameters: StrategyParameters,
        intent: ExitIntent,
        execution: ExitExecution,
        observation: LifecycleObservation,
    ) -> None:
        lifecycle_id = next(
            (
                str(row["lifecycle_id"])
                for row in reversed(self.lifecycle_events)
                if row.get("signal_id") == intent.signal_id
            ),
            _stable_id("UNKNOWN_LIFECYCLE", intent.signal_id),
        )
        root_anchor_id = next(
            (
                cast(str | None, row.get("root_anchor_id"))
                for row in reversed(self.lifecycle_events)
                if row.get("signal_id") == intent.signal_id
            ),
            None,
        )
        base = self._base(
            lifecycle_id=lifecycle_id,
            symbol=intent.symbol,
            root_anchor_id=root_anchor_id,
            rolling_base_id=observation.peak_track_id,
            signal_id=intent.signal_id,
        )
        execution_id = _stable_id("EXIT_EXECUTION", intent.intent_id)
        self._execution_row(
            base=base,
            execution_id=execution_id,
            intent_id=intent.intent_id,
            side="EXIT",
            event_type="EXIT_INTENT",
            status=execution.status.value,
            intent_at=intent.decision_at,
            event_at=intent.decision_at,
            available_at=intent.available_at,
            attempt=None,
            window=None,
            reason_codes=(intent.reason.value,),
            quantity=intent.quantity,
        )
        for attempt in execution.attempts:
            window = self._window_for_attempt(attempt)
            attempted_at = attempt.attempted_at or datetime.combine(
                attempt.trade_date, self.config.execution.next_window_end
            )
            self._execution_row(
                base=base,
                execution_id=execution_id,
                intent_id=intent.intent_id,
                side="EXIT",
                event_type="EXIT_EXECUTION_ATTEMPT",
                status="REJECTED",
                intent_at=intent.decision_at,
                event_at=attempted_at,
                available_at=attempted_at,
                attempt=attempt,
                window=window,
                reason_codes=attempt.reason_codes,
                quantity=intent.quantity,
            )
        terminal_at = execution.fill_at or (
            execution.attempts[-1].attempted_at
            if execution.attempts and execution.attempts[-1].attempted_at is not None
            else intent.decision_at
        )
        fill_window = next(
            (
                window
                for window in self._windows_by_snapshot.values()
                if execution.fill_at is not None
                and window.available_at == execution.fill_at
            ),
            None,
        )
        self._execution_row(
            base=base,
            execution_id=execution_id,
            intent_id=intent.intent_id,
            side="EXIT",
            event_type=(
                "EXIT_FILLED"
                if execution.status == ExitExecutionStatus.FILLED
                else "EXIT_DEFERRED_OR_BLOCKED"
            ),
            status=execution.status.value,
            intent_at=intent.decision_at,
            event_at=terminal_at,
            available_at=terminal_at,
            attempt=None,
            window=fill_window,
            reason_codes=execution.reason_codes,
            fill_price=execution.fill_price,
            quantity=execution.quantity,
            gross_notional=execution.gross_notional,
            commission=execution.commission,
            cash_value=execution.net_proceeds,
            blocked_tail_loss=execution.blocked_tail_loss,
        )
        if execution.status == ExitExecutionStatus.FILLED:
            self._event(
                base=base,
                event_type="LIFECYCLE_TERMINATED",
                phase="EXIT",
                state_before=ChipLifecycleState.RETEST_READY.value,
                state_after=ChipLifecycleState.NEUTRAL.value,
                decision_at=terminal_at,
                available_at=terminal_at,
                reason=intent.reason.value,
                terminal=True,
                first_failed_gate=None,
                failed_gates=(),
                snapshot_ids=execution.snapshot_ids,
                event_at=terminal_at,
            )

    def tables(self) -> LedgerTables:
        return LedgerTables(
            lifecycle_events=tuple(self.lifecycle_events),
            decision_gates=tuple(self.decision_gates),
            execution_events=tuple(self.execution_events),
            lifecycle_summary=(),
        )


def _sql_text(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _sql_files(paths: Sequence[Path]) -> str:
    return "[" + ",".join(_sql_text(str(path)) for path in paths) + "]"


def ledger_provenance(
    *,
    config: MarkupRetestConfig,
    implementation_commit: str,
) -> LedgerProvenance:
    semantic = hashlib.sha256(_canonical_json(semantic_fingerprint_fields()).encode()).hexdigest()
    artifact_contract = hashlib.sha256(
        _canonical_json(
            {
                "schema": LEDGER_SCHEMA_VERSION,
                "tables": (
                    "lifecycle_events",
                    "decision_gates",
                    "execution_events",
                    "lifecycle_summary",
                ),
            }
        ).encode()
    ).hexdigest()
    execution = hashlib.sha256(
        _canonical_json(
            {
                "decision_time": config.execution.decision_time.isoformat(),
                "next_window_end": config.execution.next_window_end.isoformat(),
                "max_entry_wait_trading_days": config.execution.max_entry_wait_trading_days,
                "nominal_capital_per_signal": config.execution.nominal_capital_per_signal,
                "fee_bps": config.execution.fee_bps,
                "slippage_bps": config.execution.slippage_bps,
                "impact_bps": config.execution.impact_bps,
                "config_sha256": config.sha256,
            }
        ).encode()
    ).hexdigest()
    return LedgerProvenance(
        frozen_root_manifest_sha256=EXPECTED_ROOT_MANIFEST_SHA256,
        frozen_lock_sha256=EXPECTED_FREEZE_LOCK_SHA256,
        v3_build_commit=EXPECTED_V3_BUILD_COMMIT,
        ledger_implementation_commit=implementation_commit,
        strategy_parameter_id=EXPECTED_PARAMETER_ID,
        strategy_version=config.strategy_version,
        semantic_fingerprint=semantic,
        artifact_contract_fingerprint=artifact_contract,
        execution_config_fingerprint=execution,
    )


def prepare_ledger_config(
    config: MarkupRetestConfig,
    *,
    symbols: Sequence[str],
    lineage_root: Path,
) -> MarkupRetestConfig:
    year = replace(config.stage(StrategyStage.YEAR), symbols=tuple(symbols))
    assets = replace(
        config.assets,
        chip_lineage_asset_id="CY-018",
        chip_lineage_root=lineage_root,
    )
    stages = dict(config.stages)
    stages[StrategyStage.YEAR] = year
    return replace(config, assets=assets, stages=stages)


def prepare_read_only_lineage_view(*, source_root: Path, work_root: Path) -> Path:
    """Build only the missing lookup index beside symlinks to registered operators."""

    view = work_root / "registered_lineage_view"
    view.mkdir(parents=True, exist_ok=False)
    for year_root in sorted(source_root.glob("year=*")):
        (view / year_root.name).symlink_to(year_root, target_is_directory=True)
    build_operator_symbol_index(view)
    return view


def build_frozen_v3_panel(
    *,
    config: MarkupRetestConfig,
    frozen_root: Path,
    symbols: Sequence[str],
    work_root: Path,
) -> tuple[Path, dict[str, Any]]:
    """Adapt frozen V3 daily candidates to the existing causal panel builder."""

    work_root.mkdir(parents=True, exist_ok=True)
    selected = tuple(symbols)
    feature_files = tuple(
        frozen_root / f"symbol={symbol}" / "daily_feature_candidate.parquet" for symbol in selected
    )
    missing = [str(path) for path in feature_files if not path.is_file()]
    if missing:
        raise FileNotFoundError("missing frozen V3 feature candidates: " + ", ".join(missing))
    inventories = {
        asset_id: verify_registered_asset_inventory(config, asset_id)
        for asset_id in ("CY-006", "CY-008", "CY-018")
    }
    minute_file = config.assets.minute_daily_file(2020)
    adapted = work_root / "adapted_frozen_v3_features.parquet"
    con = duckdb.connect()
    try:
        con.execute("SET threads = 1")
        con.execute(
            f"""
            COPY (
                SELECT
                    v.symbol,
                    v.trade_date,
                    timezone('Asia/Shanghai', v.available_at) AS available_at,
                    v.snapshot_id AS daily_snapshot_id,
                    m.snapshot_id AS minute_snapshot_id,
                    'chip-state-feature-schema-v8' AS state_version,
                    {_sql_text(config.sha256)} AS config_sha256,
                    {_sql_text(EXPECTED_V3_BUILD_COMMIT)} AS code_sha256,
                    v.research_valid AS chip_input_valid,
                    false AS daily_hard_valid,
                    coalesce(m.hard_valid, false) AS minute_hard_valid,
                    v.research_valid AS state_chain_valid,
                    'NONE' AS degraded_mode,
                    'FROZEN_V3_CHECKPOINT_JOURNAL' AS source_mode,
                    false AS action_blocking,
                    '' AS action_provenance,
                    730::BIGINT AS warmup_count,
                    false AS strict_sample,
                    1.0::DOUBLE AS mass_sum,
                    v.model_quality_min AS state_quality,
                    v.known_cost_fraction_min,
                    v.profit_ratio,
                    1.0 - v.profit_ratio AS trapped_ratio,
                    v.average_cost,
                    v.p01,
                    v.p10,
                    v.p50,
                    v.p90,
                    v.p99,
                    v.asr,
                    NULL::DOUBLE AS space20,
                    NULL::DOUBLE AS ckdp,
                    NULL::DOUBLE AS ckdw,
                    v.cbw,
                    NULL::DOUBLE AS cyqk_open_pre,
                    NULL::DOUBLE AS cyqk_close_pre,
                    NULL::DOUBLE AS cyc5,
                    NULL::DOUBLE AS cyc13,
                    NULL::DOUBLE AS cyc34,
                    NULL::DOUBLE AS cys13,
                    NULL::DOUBLE AS cys34,
                    NULL::DOUBLE AS rpy2,
                    v.concentration_20,
                    NULL::DOUBLE AS base_retention,
                    v.peak_count,
                    v.dominant_band_lower,
                    v.dominant_band_upper,
                    v.dominant_band_mass,
                    v.model_spread_cost_p50,
                    v.model_spread_cost_p90,
                    v.model_spread_dominant_peak_today AS model_spread_main_peak,
                    v.model_spread_dominant_peak_today,
                    v.tracked_base_peak,
                    v.peak_track_band_lower,
                    v.peak_track_band_upper,
                    v.peak_track_mass,
                    v.peak_track_prominence,
                    v.peak_track_id,
                    v.peak_track_ambiguous,
                    v.peak_track_split,
                    v.peak_track_merge,
                    v.peak_track_lost,
                    v.peak_definition_version,
                    v.peak_track_version,
                    m.opening_30m_return,
                    m.closing_30m_return,
                    m.close_vs_vwap,
                    m.last_hour_volume_share,
                    m.realized_volatility
                FROM read_parquet({_sql_files(feature_files)}, union_by_name=true) v
                LEFT JOIN read_parquet({_sql_text(str(minute_file))}) m
                  USING (symbol, trade_date)
                ORDER BY v.symbol, v.trade_date
            ) TO {_sql_text(str(adapted))}
            (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 65536)
            """
        )
    finally:
        con.close()

    daily_files = tuple(config.assets.daily_file(year) for year in (2018, 2019, 2020))
    corporate_actions = _resolve_corporate_action_inputs(config)
    panel_path = work_root / "frozen_v3_causal_panel.parquet"
    con = duckdb.connect()
    try:
        con.execute("SET threads = 1")
        _create_panel_table(
            con,
            config,
            StrategyStage.YEAR,
            daily_files,
            (adapted,),
            corporate_actions,
        )
        available_columns = {str(row[0]) for row in con.execute("DESCRIBE causal_panel").fetchall()}
        columns = ", ".join(
            f'"{column}"' if column in available_columns else f'NULL AS "{column}"'
            for column in _SIGNAL_INPUT_COLUMNS
        )
        con.execute(
            f"""
            COPY (
                SELECT {columns}
                FROM causal_panel
                ORDER BY symbol, trade_date
            ) TO {_sql_text(str(panel_path))}
            (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 65536)
            """
        )
        counts = con.execute(
            """
            SELECT count(*), count(DISTINCT symbol),
                   count(*) FILTER (WHERE research_hard_valid),
                   count(*) FILTER (WHERE strict_hard_valid)
            FROM causal_panel
            """
        ).fetchone()
    finally:
        con.close()
    assert counts is not None
    return panel_path, {
        "rows": int(counts[0]),
        "symbols": int(counts[1]),
        "research_hard_valid_rows": int(counts[2]),
        "strict_hard_valid_rows": int(counts[3]),
        "registered_inventories": inventories,
        "corporate_action_snapshot_id": corporate_actions.snapshot_id,
        "adapted_feature_sha256": _sha256(adapted),
        "panel_sha256": _sha256(panel_path),
    }


def _merge_ledger_tables(items: Sequence[LedgerTables]) -> LedgerTables:
    lifecycle = tuple(row for item in items for row in item.lifecycle_events)
    gates = tuple(row for item in items for row in item.decision_gates)
    execution = tuple(row for item in items for row in item.execution_events)
    return LedgerTables(
        lifecycle_events=lifecycle,
        decision_gates=gates,
        execution_events=execution,
        lifecycle_summary=build_lifecycle_summary(lifecycle, gates, execution),
    )


def build_lifecycle_summary(
    lifecycle_events: Sequence[Mapping[str, Any]],
    decision_gates: Sequence[Mapping[str, Any]],
    execution_events: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    actual_ids = sorted(
        {
            str(row["lifecycle_id"])
            for row in lifecycle_events
            if row.get("root_anchor_id") is not None
        }
    )
    events_by_id: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    gates_by_id: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    execution_by_id: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in lifecycle_events:
        events_by_id[str(row["lifecycle_id"])].append(row)
    for row in decision_gates:
        gates_by_id[str(row["lifecycle_id"])].append(row)
    for row in execution_events:
        execution_by_id[str(row["lifecycle_id"])].append(row)

    def event_time(rows: Sequence[Mapping[str, Any]], event_type: str) -> str | None:
        return next(
            (str(row["event_at"]) for row in rows if row["event_type"] == event_type),
            None,
        )

    def execution_time(rows: Sequence[Mapping[str, Any]], event_type: str) -> str | None:
        return next(
            (str(row["decision_at"]) for row in rows if row["event_type"] == event_type),
            None,
        )

    output: list[dict[str, Any]] = []
    for lifecycle_id in actual_ids:
        events = sorted(
            events_by_id[lifecycle_id], key=lambda row: (row["event_at"], row["event_id"])
        )
        gates = sorted(
            gates_by_id[lifecycle_id], key=lambda row: (row["decision_at"], row["gate_order"])
        )
        executions = sorted(
            execution_by_id[lifecycle_id],
            key=lambda row: (row["decision_at"], row["execution_event_id"]),
        )
        first = events[0]
        failed = tuple(
            dict.fromkeys(
                str(row["gate_name"])
                for row in gates
                if row.get("blocking") and not row.get("passed")
            )
        )
        output.append(
            {
                "lifecycle_id": lifecycle_id,
                "symbol": first["symbol"],
                "root_anchor_id": first["root_anchor_id"],
                "setup_time": event_time(events, "SETUP_OBSERVED"),
                "breakout_time": event_time(events, "BREAKOUT_OBSERVED"),
                "retest_time": event_time(events, "RETEST_OBSERVED"),
                "qualified": any(row["event_type"] == "QUALIFIED" for row in events),
                "first_failed_gate": failed[0] if failed else None,
                "all_failed_gates_json": _canonical_json(failed),
                "entry_intent_time": execution_time(executions, "ENTRY_INTENT"),
                "entry_execution_time": execution_time(executions, "ENTRY_FILLED"),
                "exit_intent_time": execution_time(executions, "EXIT_INTENT"),
                "exit_execution_time": execution_time(executions, "EXIT_FILLED"),
                "terminal_state": events[-1]["state_after"],
                **{
                    key: first[key]
                    for key in _provenance_columns(
                        LedgerProvenance(
                            frozen_root_manifest_sha256=str(first["frozen_root_manifest_sha256"]),
                            frozen_lock_sha256=str(first["frozen_lock_sha256"]),
                            v3_build_commit=str(first["v3_build_commit"]),
                            ledger_implementation_commit=str(first["ledger_implementation_commit"]),
                            strategy_parameter_id=str(first["strategy_parameter_id"]),
                            strategy_version=str(first["strategy_version"]),
                            semantic_fingerprint=str(first["semantic_fingerprint"]),
                            artifact_contract_fingerprint=str(
                                first["artifact_contract_fingerprint"]
                            ),
                            execution_config_fingerprint=str(first["execution_config_fingerprint"]),
                            ledger_schema_version=str(first["ledger_schema_version"]),
                        )
                    )
                },
            }
        )
    return tuple(output)


def replay_frozen_panel(
    *,
    config: MarkupRetestConfig,
    panel_path: Path,
    symbols: Sequence[str],
    provenance: LedgerProvenance,
    collect_ledger: bool = True,
) -> tuple[ExactReplayResult, LedgerTables]:
    parameters = accepted_strategy_parameters()
    execution_file = config.assets.execution_file(2020)
    market_dates = _market_trading_dates(
        (execution_file,), start=date(2020, 1, 2), end=date(2020, 12, 31)
    )
    windows_by_symbol: dict[str, list[ExecutionWindow]] = defaultdict(list)
    for window in _stream_execution_windows((execution_file,), tuple(range(32)), symbols=symbols):
        windows_by_symbol[window.symbol].append(window)
    resolver = (
        StreamingLineageSession(config.assets.chip_lineage_root)
        if config.assets.chip_lineage_root is not None
        else None
    )
    results: list[ExactReplayResult] = []
    table_items: list[LedgerTables] = []
    records = stream_panel((panel_path,), symbols=symbols, strict_schema=False)
    for symbol, raw_group in groupby(records, key=lambda row: str(row["symbol"])):
        symbol_records = tuple(raw_group)
        symbol_windows = tuple(windows_by_symbol.get(symbol, ()))
        collector = (
            LifecycleLedgerCollector(
                config=config,
                parameters=parameters,
                provenance=provenance,
                windows=symbol_windows,
                anchor_retention_resolver=resolver,
            )
            if collect_ledger
            else None
        )
        results.append(
            evaluate_exact_parameter_lattice_symbol(
                symbol_records,
                symbol_windows,
                market_dates,
                config,
                (parameters,),
                panel_snapshot_id=provenance.frozen_root_manifest_sha256,
                anchor_retention_resolver=resolver,
                audit_sink=collector,
            )
        )
        if collector is not None:
            table_items.append(collector.tables())
        if resolver is not None:
            resolver.release_symbol(symbol)
    merged_result = ExactReplayResult(
        parameters=(parameters,),
        input_rows=sum(item.input_rows for item in results),
        evaluation_rows=sum(item.evaluation_rows for item in results),
        panel_passes=sum(item.panel_passes for item in results),
        signals=tuple(row for item in results for row in item.signals),
        trades=tuple(row for item in results for row in item.trades),
        open_exposures=tuple(row for item in results for row in item.open_exposures),
    )
    return merged_result, _merge_ledger_tables(table_items)


_PROVENANCE_FIELDS = (
    ("frozen_root_manifest_sha256", pa.string()),
    ("frozen_lock_sha256", pa.string()),
    ("v3_build_commit", pa.string()),
    ("ledger_implementation_commit", pa.string()),
    ("strategy_parameter_id", pa.string()),
    ("strategy_version", pa.string()),
    ("semantic_fingerprint", pa.string()),
    ("artifact_contract_fingerprint", pa.string()),
    ("execution_config_fingerprint", pa.string()),
    ("ledger_schema_version", pa.string()),
)
_BASE_FIELDS = (
    ("lifecycle_id", pa.string()),
    ("symbol", pa.string()),
    ("root_anchor_id", pa.string()),
    ("rolling_structural_base_id", pa.string()),
    ("signal_id", pa.string()),
    *_PROVENANCE_FIELDS,
)
_LIFECYCLE_SCHEMA = pa.schema(
    (
        ("event_id", pa.string()),
        *_BASE_FIELDS,
        ("event_type", pa.string()),
        ("phase", pa.string()),
        ("state_before", pa.string()),
        ("state_after", pa.string()),
        ("decision_at", pa.string()),
        ("available_at", pa.string()),
        ("event_at", pa.string()),
        ("transition_reason", pa.string()),
        ("terminal", pa.bool_()),
        ("first_failed_gate", pa.string()),
        ("failed_gates_json", pa.string()),
        ("snapshot_ids_json", pa.string()),
        ("details_json", pa.string()),
    )
)
_GATE_SCHEMA = pa.schema(
    (
        ("gate_id", pa.string()),
        *_BASE_FIELDS,
        ("gate_order", pa.int64()),
        ("phase", pa.string()),
        ("gate_name", pa.string()),
        ("observed_json", pa.string()),
        ("observed_number", pa.float64()),
        ("observed_bool", pa.bool_()),
        ("observed_text", pa.string()),
        ("operator", pa.string()),
        ("threshold_json", pa.string()),
        ("passed", pa.bool_()),
        ("blocking", pa.bool_()),
        ("first_failed", pa.bool_()),
        ("source_function", pa.string()),
        ("reason_code", pa.string()),
        ("decision_at", pa.string()),
        ("available_at", pa.string()),
        ("is_evaluation", pa.bool_()),
        ("snapshot_ids_json", pa.string()),
    )
)
_EXECUTION_SCHEMA = pa.schema(
    (
        ("execution_event_id", pa.string()),
        *_BASE_FIELDS,
        ("execution_id", pa.string()),
        ("intent_id", pa.string()),
        ("side", pa.string()),
        ("event_type", pa.string()),
        ("status", pa.string()),
        ("intent_at", pa.string()),
        ("decision_at", pa.string()),
        ("available_at", pa.string()),
        ("execution_at", pa.string()),
        ("trade_date", pa.string()),
        ("window_index", pa.int64()),
        ("window_snapshot_id", pa.string()),
        ("window_open", pa.float64()),
        ("window_high", pa.float64()),
        ("window_low", pa.float64()),
        ("window_close", pa.float64()),
        ("window_vwap", pa.float64()),
        ("up_limit_price", pa.float64()),
        ("down_limit_price", pa.float64()),
        ("trade_status", pa.int64()),
        ("reason_codes_json", pa.string()),
        ("fill_price", pa.float64()),
        ("quantity", pa.int64()),
        ("gross_notional", pa.float64()),
        ("commission", pa.float64()),
        ("cash_value", pa.float64()),
        ("blocked_tail_loss", pa.float64()),
    )
)
_SUMMARY_SCHEMA = pa.schema(
    (
        ("lifecycle_id", pa.string()),
        ("symbol", pa.string()),
        ("root_anchor_id", pa.string()),
        ("setup_time", pa.string()),
        ("breakout_time", pa.string()),
        ("retest_time", pa.string()),
        ("qualified", pa.bool_()),
        ("first_failed_gate", pa.string()),
        ("all_failed_gates_json", pa.string()),
        ("entry_intent_time", pa.string()),
        ("entry_execution_time", pa.string()),
        ("exit_intent_time", pa.string()),
        ("exit_execution_time", pa.string()),
        ("terminal_state", pa.string()),
        *_PROVENANCE_FIELDS,
    )
)


def _write_parquet(
    path: Path,
    rows: Sequence[Mapping[str, Any]],
    schema: pa.Schema,
    *,
    sort_keys: Sequence[str],
) -> None:
    ordered = sorted(rows, key=lambda row: tuple(str(row.get(key) or "") for key in sort_keys))
    table = pa.Table.from_pylist([dict(row) for row in ordered], schema=schema)
    pq.write_table(
        table,
        path,
        compression="zstd",
        use_dictionary=False,
        write_statistics=True,
        data_page_version="1.0",
        row_group_size=65_536,
    )


def write_ledger_artifacts(
    *,
    output_root: Path,
    tables: LedgerTables,
    provenance: LedgerProvenance,
    panel_metadata: Mapping[str, Any],
    freeze_verification: Mapping[str, Any],
) -> LedgerArtifactResult:
    if output_root.exists():
        raise FileExistsError(f"ledger output already exists: {output_root}")
    output_root.mkdir(parents=True)
    specifications = (
        (
            "lifecycle_events.parquet",
            tables.lifecycle_events,
            _LIFECYCLE_SCHEMA,
            ("symbol", "decision_at", "event_at", "event_id"),
        ),
        (
            "decision_gates.parquet",
            tables.decision_gates,
            _GATE_SCHEMA,
            ("symbol", "decision_at", "gate_order", "gate_id"),
        ),
        (
            "execution_events.parquet",
            tables.execution_events,
            _EXECUTION_SCHEMA,
            ("symbol", "decision_at", "execution_event_id"),
        ),
        (
            "lifecycle_summary.parquet",
            tables.lifecycle_summary,
            _SUMMARY_SCHEMA,
            ("symbol", "setup_time", "lifecycle_id"),
        ),
    )
    artifact_hashes: dict[str, str] = {}
    row_counts: dict[str, int] = {}
    for name, rows, schema, sort_keys in specifications:
        path = output_root / name
        _write_parquet(path, rows, schema, sort_keys=sort_keys)
        artifact_hashes[name] = _sha256(path)
        row_counts[name] = len(rows)
    event_counts = Counter(str(row["event_type"]) for row in tables.lifecycle_events)
    execution_counts = Counter(str(row["event_type"]) for row in tables.execution_events)
    failed_gate_counts = Counter(
        str(row["gate_name"])
        for row in tables.decision_gates
        if row["blocking"] and not row["passed"]
    )
    summary_counts = {
        **{f"lifecycle_event:{key}": value for key, value in sorted(event_counts.items())},
        **{f"execution_event:{key}": value for key, value in sorted(execution_counts.items())},
        **{f"failed_gate:{key}": value for key, value in sorted(failed_gate_counts.items())},
    }
    manifest = {
        "status": "COMPLETE",
        "artifact_kind": "POST_HOC_REPLAY_ARTIFACT",
        "append_only": True,
        "provenance": asdict(provenance),
        "semantic_contract": semantic_fingerprint_fields(),
        "panel_metadata": dict(panel_metadata),
        "freeze_verification": dict(freeze_verification),
        "artifacts": {
            name: {"rows": row_counts[name], "sha256": artifact_hashes[name]}
            for name in sorted(artifact_hashes)
        },
        "summary_counts": summary_counts,
    }
    manifest_path = output_root / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return LedgerArtifactResult(
        output_root=output_root,
        manifest_path=manifest_path,
        artifact_hashes=artifact_hashes,
        row_counts=row_counts,
        summary_counts=summary_counts,
    )


def ledger_tables_sha256(tables: LedgerTables) -> str:
    payload = {
        "lifecycle_events": sorted(tables.lifecycle_events, key=lambda row: row["event_id"]),
        "decision_gates": sorted(tables.decision_gates, key=lambda row: row["gate_id"]),
        "execution_events": sorted(
            tables.execution_events, key=lambda row: row["execution_event_id"]
        ),
        "lifecycle_summary": sorted(tables.lifecycle_summary, key=lambda row: row["lifecycle_id"]),
    }
    return hashlib.sha256(_canonical_json(payload).encode()).hexdigest()
