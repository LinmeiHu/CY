from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone

import pytest

from cyq_game.chip.ensemble_v2 import AnchorRetentionEstimate
from cyq_game.domain import ChipLifecycleState, ExitReason, FutureDataError
from cyq_game.strategy.markup_retest import (
    FORBIDDEN_SIGNAL_FIELDS,
    ChipMassProfile,
    LifecycleMachine,
    LifecycleMemory,
    LifecycleObservation,
    assert_no_label_access,
    load_markup_retest_config,
)

CN_TZ = timezone(timedelta(hours=8))


@pytest.fixture(scope="module")
def machine() -> LifecycleMachine:
    return LifecycleMachine(load_markup_retest_config())


def _observation(
    day: date,
    *,
    setup_score: float = 0.8,
    breakout_excess_atr: float = 0.0,
    support_regained: bool = True,
    downside_absorption: bool = True,
    distribution_score: float = 0.0,
    tradable: bool = True,
    hard_valid: bool = True,
    structure_broken: bool = False,
    close: float = 10.2,
    close_vs_vwap: float = 0.01,
    market_state: str = "RISK_ON",
    sector_state: str = "STRONG",
    chip_model_disagreement_atr: float = 0.0,
) -> LifecycleObservation:
    decision_at = datetime.combine(day, time(15, 30), CN_TZ)
    return LifecycleObservation(
        symbol="000001.SZ",
        decision_at=decision_at,
        available_at=decision_at,
        snapshot_ids=(f"daily-{day}", f"chip-{day}"),
        hard_valid=hard_valid,
        tradable=tradable,
        pit_grade="B_RESEARCH_ONLY",
        setup_score=setup_score,
        breakout_excess_atr=breakout_excess_atr,
        support_regained=support_regained,
        downside_absorption=downside_absorption,
        chip_profile=ChipMassProfile.from_histogram(
            prices=(9.5, 9.8, 10.2),
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
        low=9.9,
        volume=50.0,
        turnover=0.05,
        average_cost=9.8,
        cost_p50=9.8,
        main_peak=9.8,
        prior_average_cost=9.5,
        prior_cost_p50=9.5,
        prior_main_peak=9.5,
        atr=1.0,
        chip_model_disagreement_atr=chip_model_disagreement_atr,
        structure_broken=structure_broken,
        market_state=market_state,
        sector_state=sector_state,
        industry_pit_grade="B_RESEARCH_ONLY",
        evidence_for=("setup evidence",),
        evidence_against=("market reversal",),
        alternative_explanations=("passive flow",),
    )


def _with_anchor_lineage(
    observation: LifecycleObservation,
    memory: LifecycleMemory,
    *,
    retention: float = 0.8,
) -> LifecycleObservation:
    anchor = memory.accumulation_anchor
    assert anchor is not None
    estimate = AnchorRetentionEstimate.from_model_retentions(
        anchor_id=anchor.anchor_id,
        symbol=observation.symbol,
        anchor_date=anchor.created_at,
        current_date=observation.decision_at.date(),
        model_retentions={
            "UNIFORM": retention,
            "DISPOSITION": retention,
            "ACTIVE_STICKY": retention,
        },
        ensemble_version="test-v1",
    )
    return replace(observation, anchor_retention_estimates=(estimate,))


def _form_signal(machine: LifecycleMachine) -> LifecycleMemory:
    day0 = date(2020, 6, 15)
    accumulating = machine.advance(
        LifecycleMemory(), _observation(day0), trading_index=0
    )
    assert accumulating.memory.state == ChipLifecycleState.ACCUMULATING
    breakout_observation = replace(
        _observation(day0 + timedelta(days=1), breakout_excess_atr=0.3),
        volume=100.0,
        turnover=0.10,
    )
    breakout = machine.advance(
        accumulating.memory, breakout_observation, trading_index=1
    )
    assert breakout.memory.state == ChipLifecycleState.BREAKOUT
    retest_observation = _with_anchor_lineage(
        _observation(day0 + timedelta(days=2)), breakout.memory
    )
    retest = machine.advance(breakout.memory, retest_observation, trading_index=2)
    assert retest.signal is not None
    assert retest.signal.execution_status == "BLOCKED_UNCALIBRATED"
    assert not retest.signal.order_authorized
    assert retest.memory.state == ChipLifecycleState.RETEST_READY
    return retest.memory


def test_signal_generator_rejects_any_label_columns() -> None:
    assert_no_label_access({"symbol": "000001.SZ", "setup_score": 0.8})
    with pytest.raises(FutureDataError, match="return_20d"):
        assert_no_label_access(
            {"symbol": "000001.SZ", "setup_score": 0.8, "return_20d": 0.3}
        )


@pytest.mark.parametrize("label_field", sorted(FORBIDDEN_SIGNAL_FIELDS))
def test_every_registered_label_field_is_rejected(label_field: str) -> None:
    with pytest.raises(FutureDataError, match=label_field):
        assert_no_label_access({"symbol": "000001.SZ", label_field: 1.0})


def test_accumulation_breakout_retest_is_a_causal_multi_stage_signal(
    machine: LifecycleMachine,
) -> None:
    _form_signal(machine)


def test_entry_is_blocked_when_chip_model_interval_exceeds_risk_budget(
    machine: LifecycleMachine,
) -> None:
    day0 = date(2020, 6, 15)
    accumulating = machine.advance(
        LifecycleMemory(), _observation(day0), trading_index=0
    )
    breakout = machine.advance(
        accumulating.memory,
        replace(
            _observation(day0 + timedelta(days=1), breakout_excess_atr=0.3),
            volume=100.0,
            turnover=0.10,
        ),
        trading_index=1,
    )
    ambiguous = _with_anchor_lineage(
        _observation(
            day0 + timedelta(days=2),
            chip_model_disagreement_atr=3.01,
        ),
        breakout.memory,
    )
    result = machine.advance(breakout.memory, ambiguous, trading_index=2)
    assert result.signal is None
    assert result.memory.state == ChipLifecycleState.BREAKOUT


def test_main_peak_may_hold_its_bucket_while_continuous_costs_migrate(
    machine: LifecycleMachine,
) -> None:
    day0 = date(2020, 6, 15)
    accumulating = machine.advance(
        LifecycleMemory(), _observation(day0), trading_index=0
    )
    breakout = machine.advance(
        accumulating.memory,
        replace(
            _observation(day0 + timedelta(days=1), breakout_excess_atr=0.3),
            volume=100.0,
            turnover=0.10,
        ),
        trading_index=1,
    )
    retest_observation = _with_anchor_lineage(
        replace(_observation(day0 + timedelta(days=2)), main_peak=9.5),
        breakout.memory,
    )
    result = machine.advance(
        breakout.memory, retest_observation, trading_index=2
    )
    assert result.signal is not None
    assert result.memory.state == ChipLifecycleState.RETEST_READY


def test_main_peak_must_not_migrate_lower(
    machine: LifecycleMachine,
) -> None:
    day0 = date(2020, 6, 15)
    accumulating = machine.advance(
        LifecycleMemory(), _observation(day0), trading_index=0
    )
    breakout = machine.advance(
        accumulating.memory,
        replace(
            _observation(day0 + timedelta(days=1), breakout_excess_atr=0.3),
            volume=100.0,
            turnover=0.10,
        ),
        trading_index=1,
    )
    retest_observation = _with_anchor_lineage(
        replace(_observation(day0 + timedelta(days=2)), main_peak=9.0),
        breakout.memory,
    )
    result = machine.advance(
        breakout.memory, retest_observation, trading_index=2
    )
    assert result.signal is None
    assert result.memory.state == ChipLifecycleState.BREAKOUT


def test_price_far_above_support_is_not_a_retest(machine: LifecycleMachine) -> None:
    day0 = date(2020, 6, 15)
    accumulating = machine.advance(
        LifecycleMemory(), _observation(day0), trading_index=0
    )
    breakout = machine.advance(
        accumulating.memory,
        replace(
            _observation(day0 + timedelta(days=1), breakout_excess_atr=0.3),
            volume=100.0,
            turnover=0.10,
        ),
        trading_index=1,
    )
    far_above = _with_anchor_lineage(
        replace(_observation(day0 + timedelta(days=2)), low=12.0),
        breakout.memory,
    )
    result = machine.advance(breakout.memory, far_above, trading_index=2)
    assert result.signal is None
    assert result.memory.state == ChipLifecycleState.BREAKOUT


def test_price_may_hold_above_cost_band_after_breakout(machine: LifecycleMachine) -> None:
    day0 = date(2020, 6, 15)
    accumulating = machine.advance(
        LifecycleMemory(), _observation(day0), trading_index=0
    )
    breakout = machine.advance(
        accumulating.memory,
        replace(
            _observation(day0 + timedelta(days=1), breakout_excess_atr=0.3),
            volume=100.0,
            turnover=0.10,
        ),
        trading_index=1,
    )
    extended = _with_anchor_lineage(
        replace(
            _observation(day0 + timedelta(days=2)),
            close=12.0,
            low=9.9,
            close_vs_vwap=0.01,
        ),
        breakout.memory,
    )
    result = machine.advance(breakout.memory, extended, trading_index=2)
    assert result.signal is not None
    assert result.memory.state == ChipLifecycleState.RETEST_READY


def test_retest_requires_current_downside_absorption(machine: LifecycleMachine) -> None:
    day0 = date(2020, 6, 15)
    accumulating = machine.advance(
        LifecycleMemory(), _observation(day0), trading_index=0
    )
    breakout = machine.advance(
        accumulating.memory,
        replace(
            _observation(day0 + timedelta(days=1), breakout_excess_atr=0.3),
            volume=100.0,
            turnover=0.10,
        ),
        trading_index=1,
    )
    no_absorption = _with_anchor_lineage(
        _observation(day0 + timedelta(days=2), downside_absorption=False),
        breakout.memory,
    )
    result = machine.advance(breakout.memory, no_absorption, trading_index=2)
    assert result.signal is None


def test_failed_breakout_enters_cooldown(machine: LifecycleMachine) -> None:
    day0 = date(2020, 6, 15)
    accumulating = machine.advance(
        LifecycleMemory(), _observation(day0), trading_index=0
    )
    breakout = machine.advance(
        accumulating.memory,
        replace(
            _observation(day0 + timedelta(days=1), breakout_excess_atr=0.3),
            volume=100.0,
            turnover=0.10,
        ),
        trading_index=1,
    )
    expired = machine.advance(
        breakout.memory,
        _with_anchor_lineage(_observation(day0 + timedelta(days=20)), breakout.memory),
        trading_index=12,
    )
    assert expired.memory.state == ChipLifecycleState.NEUTRAL
    assert expired.memory.cooldown_remaining == machine.config.windows.cooldown


def test_accumulation_anchor_expires_after_180_trading_days(
    machine: LifecycleMachine,
) -> None:
    started = machine.advance(
        LifecycleMemory(), _observation(date(2020, 1, 2)), trading_index=0
    )
    expired = machine.advance(
        started.memory,
        _observation(date(2020, 10, 1), setup_score=0.0),
        trading_index=181,
    )
    assert expired.memory.state == ChipLifecycleState.NEUTRAL
    assert expired.memory.accumulation_anchor is None


@pytest.mark.parametrize(
    ("market_state", "sector_state"),
    (("RISK_OFF", "STRONG"), ("RISK_ON", "WEAK"), ("UNKNOWN", "STRONG")),
)
def test_market_and_sector_risk_gate_blocks_entry(
    machine: LifecycleMachine, market_state: str, sector_state: str
) -> None:
    day0 = date(2020, 6, 15)
    accumulating = machine.advance(
        LifecycleMemory(), _observation(day0), trading_index=0
    )
    breakout = machine.advance(
        accumulating.memory,
        replace(
            _observation(day0 + timedelta(days=1), breakout_excess_atr=0.3),
            volume=100.0,
            turnover=0.10,
        ),
        trading_index=1,
    )
    retest = machine.advance(
        breakout.memory,
        _observation(
            day0 + timedelta(days=2),
            market_state=market_state,
            sector_state=sector_state,
        ),
        trading_index=2,
    )

    assert retest.signal is None
    assert retest.memory.state == ChipLifecycleState.BREAKOUT


def test_suspension_preserves_open_state_and_counters(machine: LifecycleMachine) -> None:
    opened = _form_signal(machine)
    suspended = machine.advance(
        opened,
        _observation(date(2020, 6, 18), tradable=False, distribution_score=1.0),
        trading_index=3,
    )

    assert suspended.memory == opened
    assert suspended.exit_reason is None


def test_distribution_requires_two_days_and_soft_exit_can_cancel(
    machine: LifecycleMachine,
) -> None:
    opened = _form_signal(machine)
    first = machine.advance(
        opened,
        _with_anchor_lineage(
            _observation(date(2020, 6, 18), distribution_score=0.8), opened
        ),
        trading_index=3,
    )
    assert first.memory.state == ChipLifecycleState.DISTRIBUTING
    assert first.exit_reason is None

    recovered = machine.advance(
        first.memory,
        _with_anchor_lineage(
            _observation(date(2020, 6, 19), distribution_score=0.2), first.memory
        ),
        trading_index=4,
    )
    assert recovered.memory.state == ChipLifecycleState.RETEST_READY
    assert recovered.soft_exit_cancelled
    assert recovered.exit_reason is None

    again = machine.advance(
        recovered.memory,
        _with_anchor_lineage(
            _observation(date(2020, 6, 22), distribution_score=0.8),
            recovered.memory,
        ),
        trading_index=5,
    )
    confirmed = machine.advance(
        again.memory,
        _with_anchor_lineage(
            _observation(date(2020, 6, 23), distribution_score=0.8), again.memory
        ),
        trading_index=6,
    )
    assert confirmed.exit_reason == ExitReason.DISTRIBUTION_CONFIRMED


def test_price_stop_uses_protective_stop_parameter(machine: LifecycleMachine) -> None:
    opened = _form_signal(machine)
    result = machine.advance(
        opened,
        _with_anchor_lineage(
            _observation(date(2020, 6, 18), structure_broken=True, close=8.0),
            opened,
        ),
        trading_index=3,
    )
    assert result.exit_reason == ExitReason.PROTECTIVE_STOP


def test_two_atr_stop_is_not_shadowed_by_hardcoded_one_point_five() -> None:
    config = load_markup_retest_config()
    wide_stop = LifecycleMachine(
        config, replace(config.parameters, protective_stop_atr=2.0)
    )
    opened = _form_signal(wide_stop)
    result = wide_stop.advance(
        opened,
        _with_anchor_lineage(
            _observation(date(2020, 6, 18), close=8.2), opened
        ),
        trading_index=3,
    )
    assert result.exit_reason is None


def test_rolling_structure_flag_cannot_override_frozen_breakout_support(
    machine: LifecycleMachine,
) -> None:
    opened = _form_signal(machine)
    result = machine.advance(
        opened,
        _with_anchor_lineage(
            _observation(date(2020, 6, 18), structure_broken=True), opened
        ),
        trading_index=3,
    )
    assert result.exit_reason is None


def test_share_action_rebases_open_support_without_false_stop(
    machine: LifecycleMachine,
) -> None:
    opened = _form_signal(machine)
    action_day = replace(
        _observation(date(2020, 6, 18), close=5.1),
        share_multiplier=2.0,
        chip_profile=ChipMassProfile.from_histogram(
            prices=(4.75, 4.9, 5.1),
            masses=(0.2, 0.6, 0.2),
            mass_tolerance=1e-12,
        ),
        cost_p10=4.75,
        cost_p90=5.1,
        low=4.95,
        volume=100.0,
        average_cost=4.9,
        cost_p50=4.9,
        main_peak=4.9,
        prior_average_cost=4.75,
        prior_cost_p50=4.75,
        prior_main_peak=4.75,
        atr=0.5,
        structure_support=5.0,
    )
    result = machine.advance(
        opened,
        _with_anchor_lineage(action_day, opened),
        trading_index=3,
    )

    assert result.exit_reason is None
    assert result.memory.breakout_support == pytest.approx(5.0)
    assert result.memory.comparison_anchor is not None
    assert result.memory.comparison_anchor.main_peak == pytest.approx(4.9)


def test_twenty_complete_tradable_days_are_blocked_after_exit(
    machine: LifecycleMachine,
) -> None:
    memory = machine.after_exit()
    start = date(2020, 7, 1)
    for index in range(20):
        result = machine.advance(
            memory,
            _observation(start + timedelta(days=index)),
            trading_index=index,
        )
        memory = result.memory
        assert result.signal is None
        assert memory.state == ChipLifecycleState.NEUTRAL
    assert memory.cooldown_remaining == 0

    next_day = machine.advance(
        memory, _observation(start + timedelta(days=20)), trading_index=20
    )
    assert next_day.memory.state == ChipLifecycleState.ACCUMULATING


def test_nontradable_day_does_not_consume_cooldown(machine: LifecycleMachine) -> None:
    memory = machine.after_exit()
    suspended = machine.advance(
        memory,
        _observation(date(2020, 7, 1), tradable=False),
        trading_index=0,
    )
    assert suspended.memory.cooldown_remaining == 20
