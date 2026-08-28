from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import pytest

from cyq_game.chip.ensemble_v2 import AnchorRetentionEstimate
from cyq_game.domain import ChipLifecycleState, ExitReason, FutureDataError
from cyq_game.strategy.execution import (
    EntryExecutionStatus,
    ExecutionScope,
    ExecutionWindow,
    ExitExecutionStatus,
    ExitIntent,
    execute_entry,
    execute_exit,
)
from cyq_game.strategy.lifecycle_ledger import (
    EXPECTED_FREEZE_LOCK_SHA256,
    EXPECTED_ROOT_MANIFEST_SHA256,
    LifecycleLedgerCollector,
    _failed,
    _first_failed,
    accepted_strategy_parameters,
    deterministic_lifecycle_id,
    evaluate_decision_gates,
    ledger_provenance,
    load_and_validate_freeze,
    verify_frozen_files,
)
from cyq_game.strategy.markup_retest import (
    ChipMassProfile,
    LifecycleMachine,
    LifecycleMemory,
    LifecycleObservation,
    MarkupRetestConfig,
    rebase_lifecycle_memory,
)
from cyq_game.strategy.signals import _chip_profile_from_record

CN_TZ = timezone(timedelta(hours=8))


@pytest.fixture(scope="module")
def config() -> MarkupRetestConfig:
    return MarkupRetestConfig.load(
        "/Users/linmei/Documents/CY/configs/markup_retest_v1.yaml"
    )


@pytest.fixture(scope="module")
def machine(config: MarkupRetestConfig) -> LifecycleMachine:
    return LifecycleMachine(config, accepted_strategy_parameters())


def _observation(
    day: date,
    *,
    setup_score: float = 1.0,
    breakout_excess_atr: float = 0.0,
    low: float = 9.9,
    close: float = 10.2,
    volume: float = 50.0,
    turnover: float = 0.05,
    average_cost: float = 10.0,
    cost_p50: float = 10.0,
    downside_absorption: bool = True,
    close_vs_vwap: float = 0.01,
    distribution_score: float = 0.0,
    market_state: str = "RISK_ON",
    sector_state: str = "STRONG",
    chip_model_disagreement_atr: float = 0.0,
    hard_valid: bool = True,
    tradable: bool = True,
    peak_track_id: str = "rolling-base-A",
    available_at: datetime | None = None,
    share_multiplier: float = 1.0,
    cash_per_share: float = 0.0,
    corporate_action_ids: tuple[str, ...] = (),
) -> LifecycleObservation:
    decision_at = datetime.combine(day, time(15, 30), CN_TZ)
    return LifecycleObservation(
        symbol="000001.SZ",
        decision_at=decision_at,
        available_at=available_at or decision_at,
        snapshot_ids=(f"daily-{day}", f"chip-{day}"),
        hard_valid=hard_valid,
        tradable=tradable,
        pit_grade="B_RESEARCH_ONLY",
        setup_score=setup_score,
        breakout_excess_atr=breakout_excess_atr,
        support_regained=True,
        downside_absorption=downside_absorption,
        chip_profile=ChipMassProfile.from_histogram(
            prices=(9.5, 10.0, 10.2),
            masses=(0.2, 0.6, 0.2),
            mass_tolerance=1e-12,
        ),
        cost_p10=9.5,
        cost_p90=10.2,
        peak_count=1,
        recent_band_overlap=0.9,
        distribution_score=distribution_score,
        structure_support=10.0,
        close=close,
        close_vs_vwap=close_vs_vwap,
        low=low,
        volume=volume,
        turnover=turnover,
        average_cost=average_cost,
        cost_p50=cost_p50,
        prior_average_cost=9.5,
        prior_cost_p50=9.5,
        atr=1.0,
        chip_model_disagreement_atr=chip_model_disagreement_atr,
        share_multiplier=share_multiplier,
        cash_per_share=cash_per_share,
        corporate_action_ids=corporate_action_ids,
        market_state=market_state,
        sector_state=sector_state,
        industry_pit_grade="B_RESEARCH_ONLY",
        peak_track_id=peak_track_id,
        peak_track_band_lower=9.5,
        peak_track_band_upper=10.2,
        peak_track_ambiguous=False,
        peak_definition_version="canonical-chip-peak-v2",
    )


def _lineage(
    observation: LifecycleObservation,
    memory: LifecycleMemory,
    *,
    retention: float = 0.8,
) -> LifecycleObservation:
    anchor = memory.accumulation_anchor
    assert anchor is not None
    estimate = AnchorRetentionEstimate.from_model_retentions(
        anchor_id=anchor.root_anchor_id,
        symbol=observation.symbol,
        anchor_date=anchor.created_at,
        current_date=observation.decision_at.date(),
        model_retentions={
            "UNIFORM": retention,
            "DISPOSITION": retention,
            "ACTIVE_STICKY": retention,
        },
        ensemble_version="test-ledger",
    )
    return replace(observation, anchor_retention_estimates=(estimate,))


def _breakout(machine: LifecycleMachine) -> LifecycleMemory:
    day = date(2020, 6, 15)
    setup = machine.advance(LifecycleMemory(), _observation(day), trading_index=0)
    result = machine.advance(
        setup.memory,
        _observation(
            day + timedelta(days=1),
            breakout_excess_atr=0.3,
            volume=100.0,
            turnover=0.10,
        ),
        trading_index=1,
    )
    assert result.memory.state == ChipLifecycleState.BREAKOUT
    return result.memory


def _signal(machine: LifecycleMachine):
    memory = _breakout(machine)
    observation = _lineage(_observation(date(2020, 6, 17)), memory)
    result = machine.advance(memory, observation, trading_index=2)
    assert result.signal is not None
    return result.signal, result.memory, observation


def _window(
    day: date,
    *,
    hard_valid: bool = True,
    price: float = 10.0,
    down_limit: float = 9.0,
) -> ExecutionWindow:
    available_at = datetime.combine(day, time(9, 35), CN_TZ)
    return ExecutionWindow(
        symbol="000001.SZ",
        trade_date=day,
        window_index=0,
        available_at=available_at,
        open=price,
        high=price,
        low=price,
        close=price,
        volume=10_000.0,
        amount=price * 10_000.0,
        trade_status=1,
        up_limit_price=11.0,
        down_limit_price=down_limit,
        market_rule_valid=True,
        hard_valid=hard_valid,
        snapshot_id=f"window-{day}",
    )


def test_deterministic_lifecycle_id(machine: LifecycleMachine) -> None:
    anchor = _breakout(machine).accumulation_anchor
    assert anchor is not None
    assert deterministic_lifecycle_id("p", anchor) == deterministic_lifecycle_id("p", anchor)


def test_exact_root_anchor_identity(machine: LifecycleMachine) -> None:
    memory = _breakout(machine)
    assert memory.accumulation_anchor is not None
    assert memory.accumulation_anchor.root_anchor_id == memory.accumulation_anchor.anchor_id


def test_root_anchor_does_not_roll_with_v3_base(machine: LifecycleMachine) -> None:
    day = date(2020, 6, 15)
    setup = machine.advance(LifecycleMemory(), _observation(day), trading_index=0)
    root = setup.memory.accumulation_anchor
    changed = machine.advance(
        setup.memory,
        _observation(day + timedelta(days=1), peak_track_id="rolling-base-B"),
        trading_index=1,
    )
    assert changed.memory.accumulation_anchor == root


def test_accumulation_exact_replay(machine: LifecycleMachine) -> None:
    obs = _observation(date(2020, 6, 15), setup_score=1.0)
    gates = evaluate_decision_gates(machine, LifecycleMemory(), obs, trading_index=0, record={})
    score = next(gate for gate in gates if gate.name == "setup_score")
    assert (score.observed, score.threshold, score.passed) == (1.0, 1.0, True)


def test_breakout_frozen_values_exact_replay(machine: LifecycleMachine) -> None:
    memory = _breakout(machine)
    assert (
        memory.breakout_support,
        memory.breakout_atr,
        memory.breakout_volume,
        memory.breakout_turnover,
        memory.pre_breakout_average_cost,
    ) == (10.0, 1.0, 100.0, 0.10, 9.5)


def test_retest_exact_replay(machine: LifecycleMachine) -> None:
    memory = _breakout(machine)
    obs = _lineage(_observation(date(2020, 6, 17)), memory)
    gates = evaluate_decision_gates(machine, memory, obs, trading_index=2, record={})
    values = {gate.name: gate.observed for gate in gates}
    assert values["retest_depth_atr"] == pytest.approx(0.1)
    assert values["cost_migration_atr"] == pytest.approx(0.5)
    assert values["retest_volume_ratio"] == pytest.approx(0.5)
    assert values["retest_turnover_ratio"] == pytest.approx(0.5)


def test_exact_retention_replay(machine: LifecycleMachine) -> None:
    memory = _breakout(machine)
    obs = _lineage(_observation(date(2020, 6, 17)), memory, retention=0.8)
    gates = evaluate_decision_gates(machine, memory, obs, trading_index=2, record={})
    retention = next(gate for gate in gates if gate.name == "exact_root_retention")
    assert retention.observed == pytest.approx(0.8)
    assert retention.threshold == pytest.approx(0.7)


def test_deterministic_all_failed_gates(machine: LifecycleMachine) -> None:
    memory = _breakout(machine)
    obs = _lineage(
        _observation(
            date(2020, 6, 17),
            low=8.0,
            volume=200.0,
            turnover=0.2,
            average_cost=9.6,
            cost_p50=9.6,
            downside_absorption=False,
            close_vs_vwap=-0.1,
            market_state="RISK_OFF",
            sector_state="WEAK",
            chip_model_disagreement_atr=99.0,
        ),
        memory,
        retention=0.5,
    )
    gates = evaluate_decision_gates(machine, memory, obs, trading_index=2, record={})
    assert _failed(gates) == _failed(gates)
    assert len(_failed(gates)) >= 8


def test_deterministic_first_failed_gate(machine: LifecycleMachine) -> None:
    memory = _breakout(machine)
    obs = _lineage(_observation(date(2020, 6, 17), low=8.0), memory)
    gates = evaluate_decision_gates(machine, memory, obs, trading_index=2, record={})
    assert _first_failed(gates) == "retest_depth_atr"


def test_qualification_vs_entry_intent_distinction(machine: LifecycleMachine) -> None:
    signal, _, _ = _signal(machine)
    assert signal.lifecycle_state == ChipLifecycleState.RETEST_READY
    assert signal.execution_status == "BLOCKED_UNCALIBRATED"


def test_entry_intent_vs_actual_fill_distinction(
    machine: LifecycleMachine, config: MarkupRetestConfig
) -> None:
    signal, _, _ = _signal(machine)
    day = signal.decision_at.date() + timedelta(days=1)
    execution = execute_entry(
        signal,
        (_window(day),),
        market_trading_dates=(day,),
        settings=config.execution,
        scope=ExecutionScope.RESEARCH_EVENT_STUDY,
    )
    assert signal.decision_at < execution.fill_at  # type: ignore[operator]


def test_next_legal_5_minute_execution(
    machine: LifecycleMachine, config: MarkupRetestConfig
) -> None:
    signal, _, _ = _signal(machine)
    same = signal.decision_at.date()
    next_day = same + timedelta(days=1)
    execution = execute_entry(
        signal,
        (_window(same), _window(next_day)),
        market_trading_dates=(same, next_day),
        settings=config.execution,
        scope=ExecutionScope.RESEARCH_EVENT_STUDY,
    )
    assert execution.status == EntryExecutionStatus.FILLED
    assert execution.fill_at == _window(next_day).available_at


def test_blocked_or_deferred_entry(machine: LifecycleMachine, config: MarkupRetestConfig) -> None:
    signal, _, _ = _signal(machine)
    days = tuple(signal.decision_at.date() + timedelta(days=index) for index in (1, 2, 3))
    execution = execute_entry(
        signal,
        tuple(_window(day, hard_valid=False) for day in days),
        market_trading_dates=days,
        settings=config.execution,
        scope=ExecutionScope.RESEARCH_EVENT_STUDY,
    )
    assert execution.status == EntryExecutionStatus.FAILED


def test_protective_stop_replay(machine: LifecycleMachine) -> None:
    _, memory, _ = _signal(machine)
    obs = _lineage(_observation(date(2020, 6, 18), close=8.4, low=8.3), memory)
    result = machine.advance(memory, obs, trading_index=3)
    assert result.exit_reason == ExitReason.PROTECTIVE_STOP


def test_distribution_exit_replay(machine: LifecycleMachine) -> None:
    _, memory, _ = _signal(machine)
    day1 = _lineage(_observation(date(2020, 6, 18), distribution_score=0.8), memory)
    first = machine.advance(memory, day1, trading_index=3)
    day2 = _lineage(_observation(date(2020, 6, 19), distribution_score=0.8), first.memory)
    second = machine.advance(first.memory, day2, trading_index=4)
    assert second.exit_reason == ExitReason.DISTRIBUTION_CONFIRMED


def test_max_holding_exit_replay(machine: LifecycleMachine) -> None:
    _, memory, _ = _signal(machine)
    memory = replace(memory, holding_days=machine.config.windows.max_holding - 1)
    obs = _lineage(_observation(date(2020, 6, 18)), memory)
    result = machine.advance(memory, obs, trading_index=3)
    assert result.exit_reason == ExitReason.MAX_HOLDING_PERIOD


def test_exit_intent_vs_exit_fill_distinction(config: MarkupRetestConfig) -> None:
    decision = datetime(2020, 6, 17, 15, 30, tzinfo=CN_TZ)
    intent = ExitIntent(
        intent_id="exit-1",
        signal_id="signal-1",
        symbol="000001.SZ",
        decision_at=decision,
        reason=ExitReason.PROTECTIVE_STOP,
        quantity=100,
        reference_price=10.0,
        available_at=decision,
        snapshot_ids=("daily", "chip"),
        hard_valid=True,
    )
    day = date(2020, 6, 18)
    result = execute_exit(
        intent,
        (_window(day),),
        market_trading_dates=(day,),
        settings=config.execution,
    )
    assert result.status == ExitExecutionStatus.FILLED
    assert result.fill_at is not None and result.fill_at > intent.decision_at


def test_blocked_or_deferred_exit(config: MarkupRetestConfig) -> None:
    decision = datetime(2020, 6, 17, 15, 30, tzinfo=CN_TZ)
    intent = ExitIntent(
        intent_id="exit-2",
        signal_id="signal-2",
        symbol="000001.SZ",
        decision_at=decision,
        reason=ExitReason.DISTRIBUTION_CONFIRMED,
        quantity=100,
        reference_price=10.0,
        available_at=decision,
        snapshot_ids=("daily", "chip"),
        hard_valid=True,
    )
    day = date(2020, 6, 18)
    pinned = _window(day, price=9.0, down_limit=9.0)
    result = execute_exit(
        intent,
        (pinned,),
        market_trading_dates=(day,),
        settings=config.execution,
    )
    assert result.status == ExitExecutionStatus.PENDING


def test_corporate_action_coordinate_consistency(machine: LifecycleMachine) -> None:
    memory = _breakout(machine)
    root = memory.accumulation_anchor
    obs = _observation(
        date(2020, 6, 17),
        share_multiplier=2.0,
        cash_per_share=0.1,
        corporate_action_ids=("action-1",),
    )
    rebased = rebase_lifecycle_memory(memory, obs)
    assert rebased.accumulation_anchor == root
    assert rebased.comparison_anchor != root
    assert rebased.breakout_atr == pytest.approx(0.5)


def test_available_at_pit_fail_closed() -> None:
    day = date(2020, 6, 15)
    future = datetime(2020, 6, 15, 15, 31, tzinfo=CN_TZ)
    with pytest.raises(FutureDataError):
        _observation(day, available_at=future)


def test_invalid_frozen_quantiles_remain_representable_but_fail_closed(
    config: MarkupRetestConfig,
) -> None:
    profile, valid = _chip_profile_from_record(
        {
            "cost_p01": None,
            "cost_p10": 0.0,
            "cost_p50": -1.0,
            "cost_p90": None,
            "cost_p99": None,
        },
        config,
    )
    assert valid is False
    assert all(price > 0.0 for price in profile.prices)


def test_replay_repeat_exact_equality(machine: LifecycleMachine) -> None:
    obs = _observation(date(2020, 6, 15))
    first = evaluate_decision_gates(machine, LifecycleMemory(), obs, trading_index=0, record={})
    second = evaluate_decision_gates(machine, LifecycleMemory(), obs, trading_index=0, record={})
    assert first == second


def test_positive_collector_path_keeps_qualification_intents_and_fills_distinct(
    machine: LifecycleMachine, config: MarkupRetestConfig
) -> None:
    parameters = accepted_strategy_parameters()
    setup_observation = _observation(date(2020, 6, 15))
    setup = machine.advance(
        LifecycleMemory(), setup_observation, trading_index=0
    )
    breakout_observation = _observation(
        date(2020, 6, 16),
        breakout_excess_atr=0.3,
        volume=100.0,
        turnover=0.10,
    )
    breakout = machine.advance(
        setup.memory, breakout_observation, trading_index=1
    )
    retest_observation = _lineage(
        _observation(date(2020, 6, 17)), breakout.memory
    )
    qualified = machine.advance(
        breakout.memory, retest_observation, trading_index=2
    )
    assert qualified.signal is not None
    entry_day = date(2020, 6, 18)
    entry_window = _window(entry_day)
    entry = execute_entry(
        qualified.signal,
        (entry_window,),
        market_trading_dates=(entry_day,),
        settings=config.execution,
        scope=ExecutionScope.RESEARCH_EVENT_STUDY,
    )
    collector = LifecycleLedgerCollector(
        config=config,
        parameters=parameters,
        provenance=ledger_provenance(
            config=config, implementation_commit="test-commit"
        ),
        windows=(entry_window, _window(date(2020, 6, 19))),
        anchor_retention_resolver=None,
    )
    for memory_before, observation, trading_index, transition in (
        (LifecycleMemory(), setup_observation, 0, setup),
        (setup.memory, breakout_observation, 1, breakout),
        (breakout.memory, retest_observation, 2, qualified),
    ):
        collector.on_lifecycle_decision(
            parameters=parameters,
            memory_before=memory_before,
            observation=observation,
            trading_index=trading_index,
            transition=transition,
            record={},
            is_evaluation=True,
        )
    collector.on_entry_execution(
        parameters=parameters,
        signal=qualified.signal,
        execution=entry,
        observation=retest_observation,
    )
    exit_observation = _lineage(
        _observation(date(2020, 6, 18), close=8.4, low=8.3),
        qualified.memory,
    )
    exit_transition = machine.advance(
        qualified.memory, exit_observation, trading_index=3
    )
    collector.on_lifecycle_decision(
        parameters=parameters,
        memory_before=qualified.memory,
        observation=exit_observation,
        trading_index=3,
        transition=exit_transition,
        record={},
        is_evaluation=True,
    )
    exit_intent = ExitIntent(
        intent_id="exit-ledger-positive",
        signal_id=qualified.signal.signal_id,
        symbol=qualified.signal.symbol,
        decision_at=exit_observation.decision_at,
        reason=ExitReason.PROTECTIVE_STOP,
        quantity=entry.quantity,
        reference_price=exit_observation.close,
        available_at=exit_observation.available_at,
        snapshot_ids=exit_observation.snapshot_ids,
        hard_valid=True,
    )
    exit_day = date(2020, 6, 19)
    exit_execution = execute_exit(
        exit_intent,
        (_window(exit_day),),
        market_trading_dates=(exit_day,),
        settings=config.execution,
    )
    collector.on_exit_execution(
        parameters=parameters,
        intent=exit_intent,
        execution=exit_execution,
        observation=exit_observation,
    )
    tables = collector.tables()
    lifecycle_types = {row["event_type"] for row in tables.lifecycle_events}
    execution_types = {row["event_type"] for row in tables.execution_events}
    assert {"SETUP_OBSERVED", "BREAKOUT_OBSERVED", "QUALIFIED"} <= lifecycle_types
    assert {"ENTRY_INTENT", "ENTRY_FILLED", "EXIT_INTENT", "EXIT_FILLED"} <= execution_types


def _freeze_fixture(root: Path, lock_path: Path) -> None:
    (root / "manifest.json").write_text("{}", encoding="utf-8")
    lock_path.write_text(
        json.dumps(
            {
                "final_audit": {
                    "root_manifest_sha256": EXPECTED_ROOT_MANIFEST_SHA256,
                    "symbols": 500,
                    "feature_rows": 121251,
                },
                "peak_track_version": "temporal-chip-peak-v3",
                "peak_definition_version": "canonical-chip-peak-v2",
                "ordered_symbols": [f"{index:06d}.SZ" for index in range(500)],
            }
        ),
        encoding="utf-8",
    )


def test_wrong_freeze_lock_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "root"
    root.mkdir()
    lock = tmp_path / "lock.json"
    _freeze_fixture(root, lock)
    monkeypatch.setattr(
        "cyq_game.strategy.lifecycle_ledger._sha256",
        lambda path: EXPECTED_ROOT_MANIFEST_SHA256 if path.name == "manifest.json" else "wrong",
    )
    with pytest.raises(ValueError, match="freeze lock"):
        load_and_validate_freeze(
            frozen_root=root,
            freeze_lock_path=lock,
            parameters=accepted_strategy_parameters(),
        )


def test_wrong_root_manifest_rejected(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    lock = tmp_path / "lock.json"
    _freeze_fixture(root, lock)
    with pytest.raises(ValueError, match="root manifest"):
        load_and_validate_freeze(
            frozen_root=root,
            freeze_lock_path=lock,
            parameters=accepted_strategy_parameters(),
        )


def test_wrong_parameter_id_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "root"
    root.mkdir()
    lock = tmp_path / "lock.json"
    _freeze_fixture(root, lock)
    monkeypatch.setattr(
        "cyq_game.strategy.lifecycle_ledger._sha256",
        lambda path: (
            EXPECTED_ROOT_MANIFEST_SHA256
            if path.name == "manifest.json"
            else EXPECTED_FREEZE_LOCK_SHA256
        ),
    )
    wrong = replace(accepted_strategy_parameters(), setup_score_min=1.1)
    with pytest.raises(ValueError, match="parameter"):
        load_and_validate_freeze(frozen_root=root, freeze_lock_path=lock, parameters=wrong)


def test_frozen_chip_files_remain_byte_identical(tmp_path: Path) -> None:
    root = tmp_path / "root"
    symbol_root = root / "symbol=000001.SZ"
    symbol_root.mkdir(parents=True)
    artifact = symbol_root / "data.bin"
    artifact.write_bytes(b"immutable")
    artifact_hash = hashlib.sha256(artifact.read_bytes()).hexdigest()
    symbol_manifest = symbol_root / "manifest.json"
    symbol_manifest.write_text(
        json.dumps(
            {
                "artifact": {
                    "file_metadata": [
                        {
                            "relative_path": "symbol=000001.SZ/data.bin",
                            "bytes": artifact.stat().st_size,
                            "sha256": artifact_hash,
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    (root / "manifest.json").write_text("{}", encoding="utf-8")
    lock = {
        "ordered_symbols": ["000001.SZ"],
        "final_manifest_hash_bindings": {
            "per_symbol_manifest_sha256": {
                "000001.SZ": hashlib.sha256(symbol_manifest.read_bytes()).hexdigest()
            }
        },
    }
    before = artifact.read_bytes()
    verify_frozen_files(root, lock)
    assert artifact.read_bytes() == before
