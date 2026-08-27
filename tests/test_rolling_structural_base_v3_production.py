from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone

import pytest

from cyq_game.chip.peak_versions import PEAK_DEFINITION_VERSION, PEAK_TRACK_VERSION
from cyq_game.chip.peaks import (
    CanonicalPeak,
    EnsembleTemporalPeakTracker,
    TemporalPeakTracker,
)
from cyq_game.chip.state_v2 import SellerModel
from cyq_game.strategy.markup_retest import (
    ChipMassProfile,
    LifecycleObservation,
    freeze_lifecycle_anchor,
)

CN_TZ = timezone(timedelta(hours=8))


def _candidate(
    center: int,
    mass: float = 1.0,
    *,
    lower: int | None = None,
    upper: int | None = None,
) -> CanonicalPeak:
    lower = center - 1 if lower is None else lower
    upper = center + 1 if upper is None else upper
    return CanonicalPeak(
        center_bucket=center,
        center_price=float(center),
        lower_bucket=lower,
        lower_price=float(lower),
        upper_bucket=upper,
        upper_price=float(upper),
        mass=mass,
        prominence=mass / 10.0,
        width_pct=upper / lower - 1.0,
        age_mean=None,
        formation_date="2020-01-01",
    )


def test_terminal_loss_allows_a_new_track_to_become_the_rolling_base() -> None:
    tracker = TemporalPeakTracker(symbol="TEST", model="UNIFORM")

    born_a = tracker.update(as_of=date(2019, 12, 27), candidates=(_candidate(10),))
    lost_a = tracker.update(as_of=date(2019, 12, 30), candidates=())
    born_b = tracker.update(as_of=date(2019, 12, 31), candidates=(_candidate(30),))

    assert born_a.tracked_base_peak is not None
    track_a = born_a.tracked_base_peak.peak_track_id
    assert any(peak.lost and peak.peak_track_id == track_a for peak in lost_a.peaks)
    assert born_b.tracked_base_peak is not None
    assert born_b.tracked_base_peak.peak_track_id != track_a


def test_loss_observation_remains_fail_closed_before_next_day_rebinding() -> None:
    tracker = TemporalPeakTracker(symbol="TEST", model="UNIFORM")
    born_a = tracker.update(as_of=date(2019, 12, 27), candidates=(_candidate(10),))
    loss_and_birth_b = tracker.update(
        as_of=date(2019, 12, 30), candidates=(_candidate(30),)
    )
    eligible_b = tracker.update(
        as_of=date(2019, 12, 31), candidates=(_candidate(30),)
    )

    assert born_a.tracked_base_peak is not None
    track_a = born_a.tracked_base_peak.peak_track_id
    assert loss_and_birth_b.tracked_base_peak is None
    assert loss_and_birth_b.fail_closed_reason == (
        "TRACKED_BASE_PEAK_LOST_OR_AMBIGUOUS"
    )
    assert any(
        peak.lost and peak.peak_track_id == track_a
        for peak in loss_and_birth_b.peaks
    )
    born_b = next(peak for peak in loss_and_birth_b.peaks if not peak.lost)
    assert eligible_b.tracked_base_peak is not None
    assert eligible_b.tracked_base_peak.peak_track_id == born_b.peak_track_id
    assert eligible_b.tracked_base_peak.age == 2


def test_look_alike_track_after_terminal_loss_gets_a_new_identity() -> None:
    tracker = TemporalPeakTracker(symbol="TEST", model="UNIFORM")
    born_a = tracker.update(as_of=date(2019, 12, 27), candidates=(_candidate(10),))
    tracker.update(as_of=date(2019, 12, 30), candidates=())
    born_b = tracker.update(as_of=date(2019, 12, 31), candidates=(_candidate(10),))

    assert born_a.tracked_base_peak is not None
    assert born_b.tracked_base_peak is not None
    assert born_b.tracked_base_peak.peak_track_id != (
        born_a.tracked_base_peak.peak_track_id
    )


def test_repeated_a_to_b_to_c_episodes_are_unique_and_deterministic() -> None:
    path = (
        (date(2019, 12, 20), (_candidate(10),)),
        (date(2019, 12, 23), ()),
        (date(2019, 12, 24), (_candidate(20),)),
        (date(2019, 12, 25), ()),
        (date(2019, 12, 26), (_candidate(30),)),
        (date(2019, 12, 27), (_candidate(30),)),
    )

    runs = []
    for _ in range(2):
        tracker = TemporalPeakTracker(symbol="TEST", model="UNIFORM")
        runs.append(
            tuple(
                tracker.update(as_of=as_of, candidates=candidates)
                for as_of, candidates in path
            )
        )

    assert runs[0] == runs[1]
    episode_ids = tuple(
        runs[0][index].tracked_base_peak.peak_track_id  # type: ignore[union-attr]
        for index in (0, 2, 4)
    )
    assert len(set(episode_ids)) == 3
    lost_ids = {
        peak.peak_track_id
        for result in runs[0]
        for peak in result.peaks
        if peak.lost
    }
    assert set(episode_ids[:2]).issubset(lost_ids)
    assert not lost_ids.intersection(episode_ids[2:])


def test_split_and_merge_remain_fail_closed_without_rebinding_a_live_base() -> None:
    split_tracker = TemporalPeakTracker(symbol="TEST", model="UNIFORM")
    split_a = split_tracker.update(
        as_of=date(2019, 12, 26),
        candidates=(_candidate(15, lower=10, upper=20),),
    )
    split = split_tracker.update(
        as_of=date(2019, 12, 27),
        candidates=(
            _candidate(13, 0.6, lower=10, upper=15),
            _candidate(17, 0.4, lower=15, upper=20),
        ),
    )
    split_recovered = split_tracker.update(
        as_of=date(2019, 12, 30),
        candidates=(_candidate(17, lower=15, upper=20),),
    )
    assert split_a.tracked_base_peak is not None
    track_a = split_a.tracked_base_peak.peak_track_id
    assert split.tracked_base_peak is None
    assert any(peak.split and peak.peak_track_id == track_a for peak in split.peaks)
    assert split_recovered.tracked_base_peak is not None
    assert split_recovered.tracked_base_peak.peak_track_id == track_a

    merge_tracker = TemporalPeakTracker(symbol="TEST", model="UNIFORM")
    merge_a = merge_tracker.update(
        as_of=date(2019, 12, 26),
        candidates=(
            _candidate(10, 0.6, lower=8, upper=12),
            _candidate(20, 0.4, lower=18, upper=22),
        ),
    )
    merged = merge_tracker.update(
        as_of=date(2019, 12, 27),
        candidates=(_candidate(15, lower=8, upper=22),),
    )
    merge_recovered = merge_tracker.update(
        as_of=date(2019, 12, 30),
        candidates=(_candidate(15, lower=8, upper=22),),
    )
    assert merge_a.tracked_base_peak is not None
    merge_track_a = merge_a.tracked_base_peak.peak_track_id
    assert merged.tracked_base_peak is None
    assert any(
        peak.merge and peak.peak_track_id == merge_track_a for peak in merged.peaks
    )
    assert merge_recovered.tracked_base_peak is not None
    assert merge_recovered.tracked_base_peak.peak_track_id == merge_track_a


def test_legitimate_ensemble_ambiguity_remains_unresolved() -> None:
    tracker = EnsembleTemporalPeakTracker(
        symbol="TEST", models=tuple(SellerModel)
    )
    result = tracker.update(
        as_of=date(2019, 12, 27),
        candidates_by_model={
            SellerModel.ACTIVE_STICKY: (_candidate(10), _candidate(30)),
            SellerModel.DISPOSITION: (_candidate(10),),
            SellerModel.UNIFORM: (_candidate(10),),
        },
    )

    assert result.ensemble.tracked_base_peak is None
    assert result.ensemble.fail_closed_reason == "ENSEMBLE_PEAK_AMBIGUOUS"


def test_ensemble_ambiguity_stays_fail_closed_then_a_later_episode_can_bind() -> None:
    models = tuple(SellerModel)
    tracker = EnsembleTemporalPeakTracker(symbol="TEST", models=models)
    all_a = {model: (_candidate(10),) for model in models}
    first = tracker.update(
        as_of=date(2019, 12, 24), candidates_by_model=all_a
    )
    assert first.ensemble.tracked_base_peak is not None
    track_a = first.ensemble.tracked_base_peak.peak_track_id
    ambiguous = {
        SellerModel.ACTIVE_STICKY: (_candidate(10, 0.7), _candidate(30, 0.3)),
        SellerModel.DISPOSITION: (_candidate(10),),
        SellerModel.UNIFORM: (_candidate(10),),
    }
    for day in (date(2019, 12, 25), date(2019, 12, 26)):
        result = tracker.update(as_of=day, candidates_by_model=ambiguous)
        assert result.ensemble.tracked_base_peak is None
        assert result.ensemble.fail_closed_reason == "ENSEMBLE_PEAK_AMBIGUOUS"
    empty = {model: () for model in models}
    lost = tracker.update(as_of=date(2019, 12, 27), candidates_by_model=empty)
    assert any(
        peak.lost and peak.peak_track_id == track_a
        for peak in lost.ensemble.peaks
    )
    all_b = {model: (_candidate(40),) for model in models}
    rebound = tracker.update(
        as_of=date(2019, 12, 30), candidates_by_model=all_b
    )
    assert rebound.ensemble.tracked_base_peak is not None
    assert rebound.ensemble.tracked_base_peak.peak_track_id != track_a


def test_valid_seller_model_enums_are_normalized_without_missing_model_failure() -> None:
    tracker = EnsembleTemporalPeakTracker(
        symbol="TEST", models=tuple(SellerModel)
    )
    candidates = {model: (_candidate(10),) for model in SellerModel}

    result = tracker.update(
        as_of=date(2019, 12, 27), candidates_by_model=candidates
    )

    assert result.ensemble.fail_closed_reason is None
    assert result.ensemble.tracked_base_peak is not None


def test_corporate_action_preserves_live_identity_but_cannot_revive_a_dead_one() -> None:
    live_tracker = TemporalPeakTracker(symbol="TEST", model="UNIFORM")
    before = live_tracker.update(
        as_of=date(2019, 12, 27), candidates=(_candidate(10),)
    )
    assert before.tracked_base_peak is not None
    track_a = before.tracked_base_peak.peak_track_id
    live_tracker.apply_corporate_action(
        action_id="split-2-for-1", share_multiplier=2.0
    )
    after = live_tracker.update(
        as_of=date(2019, 12, 30), candidates=(_candidate(5),)
    )
    assert after.tracked_base_peak is not None
    assert after.tracked_base_peak.peak_track_id == track_a
    assert after.tracked_base_peak.age == 2

    dead_tracker = TemporalPeakTracker(symbol="TEST", model="UNIFORM")
    dead_a = dead_tracker.update(
        as_of=date(2019, 12, 27), candidates=(_candidate(10),)
    )
    assert dead_a.tracked_base_peak is not None
    dead_track_a = dead_a.tracked_base_peak.peak_track_id
    dead_tracker.update(as_of=date(2019, 12, 30), candidates=())
    dead_tracker.apply_corporate_action(
        action_id="split-2-for-1", share_multiplier=2.0
    )
    born_b = dead_tracker.update(
        as_of=date(2019, 12, 31), candidates=(_candidate(5),)
    )
    assert born_b.tracked_base_peak is not None
    assert born_b.tracked_base_peak.peak_track_id != dead_track_a


def test_strategy_root_anchor_stays_a_when_rolling_base_becomes_b() -> None:
    tracker = TemporalPeakTracker(symbol="000001.SZ", model="ENSEMBLE")
    rolling_a = tracker.update(
        as_of=date(2019, 12, 27), candidates=(_candidate(10),)
    )
    assert rolling_a.tracked_base_peak is not None
    track_a = rolling_a.tracked_base_peak.peak_track_id
    decision_at = datetime.combine(date(2019, 12, 27), time(15, 30), CN_TZ)
    observation = LifecycleObservation(
        symbol="000001.SZ",
        decision_at=decision_at,
        available_at=decision_at,
        snapshot_ids=("daily-a", "chip-a"),
        hard_valid=True,
        tradable=True,
        pit_grade="B_RESEARCH_ONLY",
        setup_score=1.0,
        breakout_excess_atr=0.0,
        support_regained=True,
        downside_absorption=True,
        chip_profile=ChipMassProfile.from_histogram(
            prices=(9.0, 10.0, 11.0),
            masses=(0.2, 0.6, 0.2),
            mass_tolerance=1e-12,
        ),
        cost_p10=9.0,
        cost_p90=11.0,
        peak_count=1,
        recent_band_overlap=1.0,
        distribution_score=0.0,
        structure_support=10.0,
        close=10.0,
        close_vs_vwap=0.0,
        low=9.5,
        volume=100.0,
        turnover=0.1,
        average_cost=10.0,
        cost_p50=10.0,
        prior_average_cost=10.0,
        prior_cost_p50=10.0,
        atr=1.0,
        peak_track_id=track_a,
        peak_track_band_lower=9.0,
        peak_track_band_upper=11.0,
        peak_track_ambiguous=False,
        peak_definition_version=PEAK_DEFINITION_VERSION,
    )
    strategy_root = freeze_lifecycle_anchor(observation)

    tracker.update(as_of=date(2019, 12, 30), candidates=())
    rolling_b = tracker.update(
        as_of=date(2019, 12, 31), candidates=(_candidate(30),)
    )
    assert rolling_b.tracked_base_peak is not None
    track_b = rolling_b.tracked_base_peak.peak_track_id
    assert track_b != track_a
    assert strategy_root.peak_track_id == track_a
    assert strategy_root.root_anchor_id == strategy_root.anchor_id


def test_checkpoint_restore_is_exact_including_a_corporate_action() -> None:
    models = tuple(SellerModel)
    all_a = {model: (_candidate(10),) for model in models}
    all_rebased_a = {model: (_candidate(5),) for model in models}
    empty = {model: () for model in models}
    all_b = {model: (_candidate(30),) for model in models}

    continuous_tracker = EnsembleTemporalPeakTracker(symbol="TEST", models=models)
    continuous_prefix = continuous_tracker.update(
        as_of=date(2019, 12, 27), candidates_by_model=all_a
    )
    continuous_tracker.apply_corporate_action(
        action_id="split-2-for-1", share_multiplier=2.0
    )
    continuous_suffix = (
        continuous_tracker.update(
            as_of=date(2019, 12, 30), candidates_by_model=all_rebased_a
        ),
        continuous_tracker.update(
            as_of=date(2019, 12, 31), candidates_by_model=empty
        ),
        continuous_tracker.update(
            as_of=date(2020, 1, 2), candidates_by_model=all_b
        ),
    )

    checkpoint_tracker = EnsembleTemporalPeakTracker(symbol="TEST", models=models)
    resumed_prefix = checkpoint_tracker.update(
        as_of=date(2019, 12, 27), candidates_by_model=all_a
    )
    checkpoint = checkpoint_tracker.continuation()
    assert all(scope.previous_peaks for scope in checkpoint.scopes)
    restored = EnsembleTemporalPeakTracker.from_continuation(
        symbol="TEST", continuation=checkpoint
    )
    restored.apply_corporate_action(
        action_id="split-2-for-1", share_multiplier=2.0
    )
    resumed_suffix = (
        restored.update(
            as_of=date(2019, 12, 30), candidates_by_model=all_rebased_a
        ),
        restored.update(as_of=date(2019, 12, 31), candidates_by_model=empty),
        restored.update(as_of=date(2020, 1, 2), candidates_by_model=all_b),
    )

    assert resumed_prefix == continuous_prefix
    assert resumed_suffix == continuous_suffix
    assert restored.continuation() == continuous_tracker.continuation()
    final_base = resumed_suffix[-1].ensemble.tracked_base_peak
    initial_base = resumed_prefix.ensemble.tracked_base_peak
    assert initial_base is not None and final_base is not None
    assert final_base.peak_track_id != initial_base.peak_track_id


def test_old_v2_tracker_continuation_is_rejected() -> None:
    tracker = EnsembleTemporalPeakTracker(symbol="TEST", models=tuple(SellerModel))
    stale = replace(
        tracker.continuation(), tracker_version="temporal-chip-peak-v2"
    )

    with pytest.raises(ValueError, match="version is incompatible"):
        EnsembleTemporalPeakTracker.from_continuation(
            symbol="TEST", continuation=stale
        )


def test_v3_bumps_track_lifecycle_version_but_not_peak_definition() -> None:
    assert PEAK_TRACK_VERSION == "temporal-chip-peak-v3"
    assert PEAK_DEFINITION_VERSION == "canonical-chip-peak-v2"
