from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from cyq_game.chip.core import ChipState, LogPriceGrid
from cyq_game.chip.features import detect_peaks
from cyq_game.chip.peaks import (
    CanonicalPeak,
    TemporalPeakTracker,
    detect_canonical_peaks,
)
from cyq_game.strategy.semantic_contract import PEAK_DEFINITION_VERSION


def _candidate(
    center: int,
    mass: float,
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
        formation_date="2026-08-25",
    )


def test_dense_features_delegate_to_canonical_price_ordered_detector() -> None:
    grid = LogPriceGrid.around(5.0, 25.0, 0.005)
    raw = np.zeros(len(grid.prices), dtype=np.float64)
    raw[len(raw) // 3] = 0.4
    raw[2 * len(raw) // 3] = 0.6
    state = ChipState(
        grid=grid,
        mass=raw,
        as_of=date(2026, 8, 25),
        engine="test",
        quality=1.0,
    )
    dense = detect_peaks(state)
    canonical = detect_canonical_peaks(
        enumerate(float(value) for value in raw),
        price_for_bucket=lambda bucket: float(grid.prices[bucket]),
        as_of=state.as_of,
    )
    assert dense == list(canonical)
    assert [peak.center_price for peak in dense] == sorted(peak.center_price for peak in dense)
    assert all(peak.definition_version == PEAK_DEFINITION_VERSION for peak in dense)


def test_peak_tuning_cannot_silently_create_an_incompatible_definition() -> None:
    grid = LogPriceGrid.around(5.0, 25.0, 0.005)
    mass = np.zeros(len(grid.prices), dtype=np.float64)
    mass[len(mass) // 2] = 1.0
    state = ChipState(grid=grid, mass=mass, as_of=date.today(), engine="test", quality=1.0)
    with pytest.raises(ValueError, match="canonical"):
        detect_peaks(state, sigma=0.8)


def test_dominant_mass_switch_does_not_change_tracked_base_identity() -> None:
    tracker = TemporalPeakTracker(symbol="000001.SZ", model="fifo")
    first = tracker.update(
        as_of=date(2026, 8, 24),
        candidates=(_candidate(10, 0.60), _candidate(20, 0.40)),
    )
    assert first.tracked_base_peak is not None
    base_id = first.tracked_base_peak.peak_track_id

    second = tracker.update(
        as_of=date(2026, 8, 25),
        candidates=(_candidate(10, 0.45), _candidate(20, 0.55)),
    )
    assert second.dominant_peak_today is not None
    assert second.tracked_base_peak is not None
    assert second.dominant_peak_today.center_price == 20.0
    assert second.tracked_base_peak.center_price == 10.0
    assert second.tracked_base_peak.peak_track_id == base_id


def test_peak_split_and_missing_base_fail_closed() -> None:
    tracker = TemporalPeakTracker(symbol="000001.SZ", model="fifo")
    first = tracker.update(as_of=date(2026, 8, 23), candidates=(_candidate(15, 0.8, 10, 20),))
    assert first.tracked_base_peak is not None
    split = tracker.update(
        as_of=date(2026, 8, 24),
        candidates=(_candidate(13, 0.4, 10, 15), _candidate(17, 0.4, 15, 20)),
    )
    assert split.tracked_base_peak is None
    assert split.fail_closed_reason == "TRACKED_BASE_PEAK_LOST_OR_AMBIGUOUS"

    missing = tracker.update(as_of=date(2026, 8, 24) + timedelta(days=1), candidates=())
    assert missing.dominant_peak_today is None
    assert missing.tracked_base_peak is None
    assert missing.fail_closed_reason == "PEAK_MISSING"
