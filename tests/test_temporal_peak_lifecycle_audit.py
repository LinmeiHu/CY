from __future__ import annotations

from datetime import date

from cyq_game.chip.peaks import CanonicalPeak, PeakTrackingResult, TemporalPeakTracker


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


def _run(
    tracker: TemporalPeakTracker,
    path: tuple[tuple[date, tuple[CanonicalPeak, ...]], ...],
) -> tuple[PeakTrackingResult, ...]:
    return tuple(
        tracker.update(as_of=as_of, candidates=candidates)
        for as_of, candidates in path
    )


def test_case_a_ordinary_continuation_preserves_identity() -> None:
    results = _run(
        TemporalPeakTracker(symbol="TEST", model="UNIFORM"),
        (
            (date(2019, 12, 27), (_candidate(10),)),
            (date(2019, 12, 30), (_candidate(10),)),
            (date(2019, 12, 31), (_candidate(10),)),
        ),
    )

    bases = tuple(result.tracked_base_peak for result in results)
    assert all(base is not None for base in bases)
    assert len({base.peak_track_id for base in bases if base is not None}) == 1
    assert [base.age for base in bases if base is not None] == [1, 2, 3]


def test_case_b_lost_identity_is_a_terminal_matching_event() -> None:
    tracker = TemporalPeakTracker(symbol="TEST", model="UNIFORM")
    first, continued, lost, unrelated = _run(
        tracker,
        (
            (date(2019, 12, 26), (_candidate(10),)),
            (date(2019, 12, 27), (_candidate(10),)),
            (date(2019, 12, 30), ()),
            (date(2019, 12, 31), (_candidate(30),)),
        ),
    )
    assert first.tracked_base_peak is not None
    assert continued.tracked_base_peak is not None
    track_a = first.tracked_base_peak.peak_track_id
    assert any(peak.lost and peak.peak_track_id == track_a for peak in lost.peaks)
    assert all(peak.peak_track_id != track_a for peak in unrelated.peaks)


def test_case_c_new_unrelated_track_is_born_but_cannot_replace_lost_v2_base() -> None:
    results = _run(
        TemporalPeakTracker(symbol="TEST", model="UNIFORM"),
        (
            (date(2019, 12, 24), (_candidate(10),)),
            (date(2019, 12, 25), (_candidate(10),)),
            (date(2019, 12, 26), ()),
            (date(2019, 12, 27), ()),
            (date(2019, 12, 30), (_candidate(30),)),
            (date(2019, 12, 31), (_candidate(30),)),
            (date(2020, 1, 2), (_candidate(30),)),
            (date(2020, 1, 3), (_candidate(30),)),
        ),
    )

    track_a = results[0].tracked_base_peak
    assert track_a is not None
    track_b_ids = tuple(result.peaks[0].peak_track_id for result in results[4:])
    assert len(set(track_b_ids)) == 1
    assert track_b_ids[0] != track_a.peak_track_id
    assert [result.peaks[0].age for result in results[4:]] == [1, 2, 3, 4]
    assert all(result.dominant_peak_today is not None for result in results[4:])
    assert all(result.tracked_base_peak is None for result in results[4:])
    assert all(
        result.fail_closed_reason == "TRACKED_BASE_PEAK_LOST_OR_AMBIGUOUS"
        for result in results[4:]
    )


def test_case_d_look_alike_reappearance_gets_a_new_identity_not_a_reattachment() -> None:
    tracker = TemporalPeakTracker(symbol="TEST", model="UNIFORM")
    born, lost, reappeared, continued = _run(
        tracker,
        (
            (date(2019, 12, 27), (_candidate(10),)),
            (date(2019, 12, 30), ()),
            (date(2019, 12, 31), (_candidate(10),)),
            (date(2020, 1, 2), (_candidate(10),)),
        ),
    )

    assert born.tracked_base_peak is not None
    track_a = born.tracked_base_peak.peak_track_id
    assert any(peak.lost and peak.peak_track_id == track_a for peak in lost.peaks)
    track_b = reappeared.peaks[0].peak_track_id
    assert track_b != track_a
    assert continued.peaks[0].peak_track_id == track_b
    assert continued.tracked_base_peak is None


def test_case_e_split_can_recover_only_through_the_continuing_base_identity() -> None:
    tracker = TemporalPeakTracker(symbol="TEST", model="UNIFORM")
    born, split, stabilized = _run(
        tracker,
        (
            (date(2019, 12, 27), (_candidate(15, lower=10, upper=20),)),
            (
                date(2019, 12, 30),
                (
                    _candidate(13, 0.6, lower=10, upper=15),
                    _candidate(17, 0.4, lower=15, upper=20),
                ),
            ),
            (date(2019, 12, 31), (_candidate(17, lower=15, upper=20),)),
        ),
    )

    assert born.tracked_base_peak is not None
    track_a = born.tracked_base_peak.peak_track_id
    assert split.tracked_base_peak is None
    assert any(peak.peak_track_id == track_a and peak.split for peak in split.peaks)
    assert stabilized.tracked_base_peak is not None
    assert stabilized.tracked_base_peak.peak_track_id == track_a


def test_case_f_merge_can_recover_only_through_the_claiming_base_identity() -> None:
    tracker = TemporalPeakTracker(symbol="TEST", model="UNIFORM")
    born, merged, stabilized = _run(
        tracker,
        (
            (
                date(2019, 12, 27),
                (
                    _candidate(10, 0.6, lower=8, upper=12),
                    _candidate(20, 0.4, lower=18, upper=22),
                ),
            ),
            (date(2019, 12, 30), (_candidate(15, lower=8, upper=22),)),
            (date(2019, 12, 31), (_candidate(15, lower=8, upper=22),)),
        ),
    )

    assert born.tracked_base_peak is not None
    track_a = born.tracked_base_peak.peak_track_id
    assert merged.tracked_base_peak is None
    assert any(peak.peak_track_id == track_a and peak.merge for peak in merged.peaks)
    assert stabilized.tracked_base_peak is not None
    assert stabilized.tracked_base_peak.peak_track_id == track_a


def test_case_g_year_boundary_has_no_semantics_when_tracker_state_continues() -> None:
    path = (
        (date(2019, 12, 27), (_candidate(10),)),
        (date(2019, 12, 30), (_candidate(10),)),
        (date(2019, 12, 31), (_candidate(10),)),
        (date(2020, 1, 2), (_candidate(10),)),
        (date(2020, 1, 3), (_candidate(10),)),
    )
    continuous = _run(
        TemporalPeakTracker(symbol="TEST", model="UNIFORM"), path
    )
    continued_tracker = TemporalPeakTracker(symbol="TEST", model="UNIFORM")
    warmup = _run(continued_tracker, path[:3])
    output = _run(continued_tracker, path[3:])

    assert (*warmup, *output) == continuous
    assert output[0].tracked_base_peak is not None
    assert output[0].tracked_base_peak.age == 4


def test_case_g_fresh_output_year_tracker_diverges_from_continued_state() -> None:
    warmup_path = (
        (date(2019, 12, 30), (_candidate(10),)),
        (date(2019, 12, 31), (_candidate(10),)),
    )
    output_path = (
        (date(2020, 1, 2), (_candidate(10),)),
        (date(2020, 1, 3), (_candidate(10),)),
    )
    continued_tracker = TemporalPeakTracker(symbol="TEST", model="UNIFORM")
    _run(continued_tracker, warmup_path)
    continued = _run(continued_tracker, output_path)
    reset = _run(
        TemporalPeakTracker(symbol="TEST", model="UNIFORM"), output_path
    )

    assert continued != reset
    assert continued[0].tracked_base_peak is not None
    assert reset[0].tracked_base_peak is not None
    assert continued[0].tracked_base_peak.age == 3
    assert reset[0].tracked_base_peak.age == 1
    assert (
        continued[0].tracked_base_peak.peak_track_id
        != reset[0].tracked_base_peak.peak_track_id
    )
