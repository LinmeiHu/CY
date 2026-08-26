from __future__ import annotations

import math
import struct
from dataclasses import replace
from datetime import date
from itertools import pairwise

import pytest

import cyq_game.chip.peaks as peak_module
from cyq_game.chip.peaks import CanonicalPeak, detect_canonical_peaks


_KERNEL = (1.0, 4.0, 6.0, 4.0, 1.0)
_OFFSETS = (-2, -1, 0, 1, 2)
_KERNEL_TOTAL = math.fsum(_KERNEL)
_MIN_PEAK_MASS = 0.03
_MIN_PROMINENCE = 0.003


def _legacy_detect_canonical_peaks(
    bucket_mass: dict[int, float], *, age_weight_by_bucket: dict[int, float] | None = None
) -> tuple[CanonicalPeak, ...]:
    """Pre-cache implementation retained only as an exact test oracle."""

    combined = {int(bucket): float(mass) for bucket, mass in bucket_mass.items() if mass > 0.0}
    if not combined:
        return ()
    total = math.fsum(combined.values())

    def price_for_bucket(bucket: int) -> float:
        return 100.0 + float(bucket)

    def smoothed(bucket: int) -> float:
        return math.fsum(
            weight * combined.get(bucket + offset, 0.0)
            for offset, weight in zip(_OFFSETS, _KERNEL, strict=True)
        ) / (_KERNEL_TOTAL * total)

    first, last = min(combined), max(combined)
    candidates = tuple(
        bucket
        for bucket in range(first, last + 1)
        if smoothed(bucket) >= smoothed(bucket - 1) and smoothed(bucket) > smoothed(bucket + 1)
    )
    result: list[CanonicalPeak] = []
    for center in candidates:
        height = smoothed(center)
        half_height = height * 0.5
        lower = center
        while lower > first and smoothed(lower - 1) >= half_height:
            lower -= 1
        upper = center
        while upper < last and smoothed(upper + 1) >= half_height:
            upper += 1
        local_mass = math.fsum(
            mass for bucket, mass in combined.items() if lower <= bucket <= upper
        ) / total
        left_floor = min(smoothed(bucket) for bucket in range(first - 1, center + 1))
        right_floor = min(smoothed(bucket) for bucket in range(center, last + 2))
        prominence = height - max(left_floor, right_floor)
        if local_mass < _MIN_PEAK_MASS or prominence < _MIN_PROMINENCE:
            continue
        age_mean: float | None = None
        if age_weight_by_bucket is not None:
            weighted_age = math.fsum(
                float(age_weight_by_bucket.get(bucket, 0.0)) for bucket in range(lower, upper + 1)
            )
            band_mass = math.fsum(combined.get(bucket, 0.0) for bucket in range(lower, upper + 1))
            age_mean = weighted_age / band_mass if band_mass > 0.0 else None
        lower_price = price_for_bucket(lower)
        upper_price = price_for_bucket(upper)
        center_price = price_for_bucket(center)
        result.append(
            CanonicalPeak(
                center_bucket=center,
                center_price=center_price,
                lower_bucket=lower,
                lower_price=lower_price,
                upper_bucket=upper,
                upper_price=upper_price,
                mass=local_mass,
                prominence=prominence,
                width_pct=upper_price / lower_price - 1.0,
                age_mean=age_mean,
                formation_date="2020-01-02",
            )
        )
    structural: list[CanonicalPeak] = []
    for peak in sorted(result, key=lambda value: (-value.prominence, -value.mass, value.center_price)):
        if any(
            existing.lower_price <= peak.center_price <= existing.upper_price
            and peak.lower_price <= existing.center_price <= peak.upper_price
            for existing in structural
        ):
            continue
        structural.append(peak)
    ordered = sorted(structural, key=lambda peak: peak.center_bucket)
    separated: list[CanonicalPeak] = []
    for peak in ordered:
        if separated:
            previous = separated[-1]
            valley = min(smoothed(bucket) for bucket in range(previous.center_bucket, peak.center_bucket + 1))
            weaker_height = min(smoothed(previous.center_bucket), smoothed(peak.center_bucket))
            if weaker_height > 0.0 and valley / weaker_height >= 0.80:
                if peak.prominence > previous.prominence:
                    separated[-1] = peak
                continue
        separated.append(peak)
    valley_boundaries = [
        min(
            range(left.center_bucket, right.center_bucket + 1),
            key=lambda bucket: (smoothed(bucket), bucket),
        )
        for left, right in pairwise(separated)
    ]
    bounded: list[CanonicalPeak] = []
    for index, peak in enumerate(separated):
        lower = peak.lower_bucket if index == 0 else valley_boundaries[index - 1] + 1
        upper = peak.upper_bucket if index == len(separated) - 1 else valley_boundaries[index]
        band_mass_raw = math.fsum(combined.get(bucket, 0.0) for bucket in range(lower, upper + 1))
        age_mean = peak.age_mean
        if age_weight_by_bucket is not None and band_mass_raw > 0.0:
            age_mean = math.fsum(
                float(age_weight_by_bucket.get(bucket, 0.0))
                for bucket in range(lower, upper + 1)
            ) / band_mass_raw
        lower_price = price_for_bucket(lower)
        upper_price = price_for_bucket(upper)
        bounded.append(
            replace(
                peak,
                lower_bucket=lower,
                lower_price=lower_price,
                upper_bucket=upper,
                upper_price=upper_price,
                mass=band_mass_raw / total,
                width_pct=upper_price / lower_price - 1.0,
                age_mean=age_mean,
            )
        )
    return tuple(bounded)


def _bits(value: float) -> bytes:
    return struct.pack("!d", value)


def _peak_bits(peaks: tuple[CanonicalPeak, ...]) -> tuple[tuple[object, ...], ...]:
    return tuple(
        (
            peak.center_bucket,
            _bits(peak.center_price),
            peak.lower_bucket,
            _bits(peak.lower_price),
            peak.upper_bucket,
            _bits(peak.upper_price),
            _bits(peak.mass),
            _bits(peak.prominence),
            _bits(peak.width_pct),
            None if peak.age_mean is None else _bits(peak.age_mean),
            peak.formation_date,
            peak.definition_version,
        )
        for peak in peaks
    )


@pytest.mark.parametrize(
    ("profile", "ages"),
    [
        ({}, None),  # empty profile
        ({0: 1.0}, {0: 5.0}),  # single bucket and boundary window
        ({0: 0.7, 5: 0.3}, None),  # sparse/non-contiguous
        ({0: 0.1, 1: 0.8, 2: 0.1}, None),  # boundary peak
        ({0: 0.1, 1: 0.3, 2: 0.3, 3: 0.1}, None),  # plateau
        ({0: 0.35, 8: 0.35, 16: 0.30}, None),  # equal-height peaks
        ({0: 0.25, 1: 0.25, 8: 0.25, 9: 0.25}, None),  # equal-prominence tie
        ({0: 0.05, 1: 0.10, 2: 0.20, 3: 0.30, 4: 0.20, 5: 0.10, 6: 0.05}, None),  # wide
        ({0: 0.30, 1: 0.02, 2: 0.30, 3: 0.02, 4: 0.36}, None),  # adjacent valleys
        ({0: 0.0001, 10: 0.9999}, None),  # minimal mass
        ({0: 0.48, 2048: 0.52}, None),  # large but valid span
        ({0: 0.20, 5: 0.50, 12: 0.30}, {0: 1.0, 5: 4.0, 12: 9.0}),  # uniform
        ({0: 0.30, 5: 0.40, 12: 0.30}, {0: 2.0, 5: 8.0, 12: 18.0}),  # disposition
        ({0: 0.45, 5: 0.10, 12: 0.45}, {0: 3.0, 5: 12.0, 12: 27.0}),  # active_sticky
    ],
)
def test_cache_is_bit_exact_against_pre_cache_reference(
    profile: dict[int, float], ages: dict[int, float] | None
) -> None:
    expected = _legacy_detect_canonical_peaks(profile, age_weight_by_bucket=ages)
    actual = detect_canonical_peaks(
        profile,
        price_for_bucket=lambda bucket: 100.0 + float(bucket),
        as_of=date(2020, 1, 2),
        age_weight_by_bucket=ages,
    )
    assert _peak_bits(actual) == _peak_bits(expected)


def test_local_cache_eliminates_repeated_smoothing_fsum_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    profile = {bucket: float((bucket % 7) + 1) for bucket in range(48)}
    original_fsum = math.fsum
    calls = 0

    def counted_fsum(values):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        return original_fsum(values)

    monkeypatch.setattr(peak_module.math, "fsum", counted_fsum)
    _legacy_detect_canonical_peaks(profile)
    legacy_calls = calls
    calls = 0
    detect_canonical_peaks(
        profile,
        price_for_bucket=lambda bucket: 100.0 + float(bucket),
        as_of=date(2020, 1, 2),
    )
    cached_calls = calls
    assert cached_calls < legacy_calls
