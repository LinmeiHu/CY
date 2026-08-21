from __future__ import annotations

from datetime import date

import numpy as np

from cyq_game.chip.core import ChipState, LogPriceGrid
from cyq_game.chip.features import ChipPeak, _gaussian_smooth, detect_peaks


def _reference_detect_peaks(
    state: ChipState,
    sigma: float,
    min_prominence: float,
) -> list[ChipPeak]:
    smooth = _gaussian_smooth(state.mass, sigma)
    left_minima = np.minimum.accumulate(smooth)
    right_minima = np.minimum.accumulate(smooth[::-1])[::-1]
    peaks: list[ChipPeak] = []
    for index in range(1, len(smooth) - 1):
        if not (smooth[index] > smooth[index - 1] and smooth[index] >= smooth[index + 1]):
            continue
        prominence = float(
            smooth[index] - max(float(left_minima[index]), float(right_minima[index]))
        )
        left = index
        right = index
        half_height = smooth[index] / 2.0
        while left > 0 and smooth[left - 1] >= half_height:
            left -= 1
        while right < len(smooth) - 1 and smooth[right + 1] >= half_height:
            right += 1
        peak_mass = float(state.mass[left : right + 1].sum())
        if peak_mass < min_prominence and prominence < min_prominence:
            continue
        age_mean: float | None = None
        if state.age_mass is not None:
            local = state.age_mass[left : right + 1]
            age_mean = float(
                np.dot(local.sum(axis=0), np.arange(local.shape[1]))
                / max(local.sum(), 1e-12)
            )
        peaks.append(
            ChipPeak(
                center_price=float(state.grid.prices[index]),
                mass=peak_mass,
                width_pct=float(state.grid.prices[right] / state.grid.prices[left] - 1.0),
                prominence=prominence,
                age_mean=age_mean,
                formation_date=state.as_of.isoformat(),
            )
        )
    return sorted(peaks, key=lambda peak: peak.mass, reverse=True)


def test_vectorized_peak_boundaries_match_reference() -> None:
    rng = np.random.default_rng(20260821)
    grid = LogPriceGrid.around(5.0, 25.0, 0.005)
    for with_cohorts in (False, True):
        for sigma in (0.0, 0.8, 1.5, 2.5):
            raw = rng.random(len(grid.prices)) ** 4
            mass = raw / raw.sum()
            age_mass = None
            if with_cohorts:
                shares = rng.dirichlet(np.ones(13), size=len(mass))
                age_mass = mass[:, None] * shares
            state = ChipState(
                grid=grid,
                mass=mass,
                as_of=date(2026, 8, 21),
                engine="test",
                quality=1.0,
                age_mass=age_mass,
            )
            actual = detect_peaks(state, sigma, 0.01)
            expected = _reference_detect_peaks(state, sigma, 0.01)
            assert len(actual) == len(expected)
            for actual_peak, expected_peak in zip(actual, expected, strict=True):
                assert actual_peak.formation_date == expected_peak.formation_date
                np.testing.assert_allclose(
                    [
                        actual_peak.center_price,
                        actual_peak.mass,
                        actual_peak.width_pct,
                        actual_peak.prominence,
                    ],
                    [
                        expected_peak.center_price,
                        expected_peak.mass,
                        expected_peak.width_pct,
                        expected_peak.prominence,
                    ],
                    rtol=1e-13,
                    atol=1e-15,
                )
                if expected_peak.age_mean is None:
                    assert actual_peak.age_mean is None
                else:
                    assert actual_peak.age_mean is not None
                    np.testing.assert_allclose(
                        actual_peak.age_mean,
                        expected_peak.age_mean,
                        rtol=1e-13,
                        atol=1e-15,
                    )
