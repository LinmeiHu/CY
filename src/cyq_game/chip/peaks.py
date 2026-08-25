"""Canonical chip-peak detection and causal temporal identity tracking."""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import date
from hashlib import sha256
from itertools import pairwise
from statistics import median

from cyq_game.chip.peak_versions import PEAK_DEFINITION_VERSION, PEAK_TRACK_VERSION
from cyq_game.chip.price_coordinate import rebase_economic_price

_KERNEL = (1.0, 4.0, 6.0, 4.0, 1.0)
_OFFSETS = (-2, -1, 0, 1, 2)
_KERNEL_TOTAL = math.fsum(_KERNEL)
_MIN_PEAK_MASS = 0.03
_MIN_PROMINENCE = 0.003
_DOMINANCE_AMBIGUITY_MASS = 0.02
_MAX_BUCKET_SPAN = 1_000_000


@dataclass(frozen=True)
class CanonicalPeak:
    """One price-ordered peak detected with the repository-wide definition."""

    center_bucket: int
    center_price: float
    lower_bucket: int
    lower_price: float
    upper_bucket: int
    upper_price: float
    mass: float
    prominence: float
    width_pct: float
    age_mean: float | None
    formation_date: str
    definition_version: str = PEAK_DEFINITION_VERSION


@dataclass(frozen=True)
class TrackedPeak:
    """A canonical peak observation carrying a causal cross-session identity."""

    peak_track_id: str
    age: int
    band: tuple[float, float]
    center_price: float
    mass: float
    prominence: float
    ambiguity: bool
    split: bool
    merge: bool
    lost: bool
    definition_version: str
    track_version: str = PEAK_TRACK_VERSION


@dataclass(frozen=True)
class PeakTrackingResult:
    peaks: tuple[TrackedPeak, ...]
    dominant_peak_today: TrackedPeak | None
    tracked_base_peak: TrackedPeak | None
    fail_closed_reason: str | None


@dataclass(frozen=True)
class EnsemblePeakTrackingResult:
    """A single ensemble track plus the seller-model-local observations."""

    ensemble: PeakTrackingResult
    by_model: Mapping[str, PeakTrackingResult]


def detect_canonical_peaks(
    bucket_mass: Mapping[int, float] | Iterable[tuple[int, float]],
    *,
    price_for_bucket: Callable[[int], float],
    as_of: date,
    age_weight_by_bucket: Mapping[int, float] | None = None,
) -> tuple[CanonicalPeak, ...]:
    """Detect peaks once, with fixed semantics, and return them in price order."""

    combined: dict[int, float] = {}
    items = bucket_mass.items() if isinstance(bucket_mass, Mapping) else bucket_mass
    for raw_bucket, raw_mass in items:
        bucket = int(raw_bucket)
        mass = float(raw_mass)
        if not math.isfinite(mass) or mass < 0.0:
            raise ValueError("peak bucket mass must be finite and non-negative")
        combined[bucket] = combined.get(bucket, 0.0) + mass
    combined = {bucket: mass for bucket, mass in combined.items() if mass > 0.0}
    if not combined:
        return ()
    if max(combined) - min(combined) > _MAX_BUCKET_SPAN:
        raise ValueError("peak bucket range is invalid or contains a sentinel")
    total = math.fsum(combined.values())
    if not math.isfinite(total) or total <= 0.0:
        raise ValueError("peak total mass must be finite and positive")

    prices: dict[int, float] = {}
    for bucket in combined:
        value = float(price_for_bucket(bucket))
        if not math.isfinite(value) or value <= 0.0:
            raise ValueError("peak prices must be finite and positive")
        prices[bucket] = value

    def smoothed(bucket: int) -> float:
        return math.fsum(
            weight * combined.get(bucket + offset, 0.0)
            for offset, weight in zip(_OFFSETS, _KERNEL, strict=True)
        ) / (_KERNEL_TOTAL * total)

    first = min(combined)
    last = max(combined)
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
        local_mass = (
            math.fsum(mass for bucket, mass in combined.items() if lower <= bucket <= upper) / total
        )
        left_floor = min(smoothed(bucket) for bucket in range(first - 1, center + 1))
        right_floor = min(smoothed(bucket) for bucket in range(center, last + 2))
        prominence = height - max(left_floor, right_floor)
        # A wide half-height band can contain most of a diffuse distribution;
        # mass alone is therefore not evidence of a structural local mode.
        # Require both material band mass and material topographic prominence.
        if local_mass < _MIN_PEAK_MASS or prominence < _MIN_PROMINENCE:
            continue
        age_mean: float | None = None
        if age_weight_by_bucket is not None:
            weighted_age = math.fsum(
                float(age_weight_by_bucket.get(bucket, 0.0)) for bucket in range(lower, upper + 1)
            )
            band_mass = math.fsum(combined.get(bucket, 0.0) for bucket in range(lower, upper + 1))
            age_mean = weighted_age / band_mass if band_mass > 0.0 else None
            if age_mean is not None and (not math.isfinite(age_mean) or age_mean < 0.0):
                raise ValueError("peak age must be finite and non-negative")
        lower_price = float(price_for_bucket(lower))
        upper_price = float(price_for_bucket(upper))
        center_price = float(price_for_bucket(center))
        if not all(
            math.isfinite(value) and value > 0.0
            for value in (lower_price, center_price, upper_price)
        ):
            raise ValueError("peak band prices must be finite and positive")
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
                formation_date=as_of.isoformat(),
            )
        )
    # Half-height shoulders inside one broad mode are not independent peaks.
    # Keep the most prominent representative whenever candidate centers fall
    # inside each other's bands; this is deterministic non-maximum suppression,
    # not a cross-day identity heuristic.
    structural: list[CanonicalPeak] = []
    for peak in sorted(
        result,
        key=lambda value: (
            -value.prominence,
            -value.mass,
            value.center_price,
        ),
    ):
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
            valley = min(
                smoothed(bucket)
                for bucket in range(previous.center_bucket, peak.center_bucket + 1)
            )
            weaker_height = min(
                smoothed(previous.center_bucket), smoothed(peak.center_bucket)
            )
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
        band_mass_raw = math.fsum(
            combined.get(bucket, 0.0) for bucket in range(lower, upper + 1)
        )
        band_mass = band_mass_raw / total
        age_mean = peak.age_mean
        if age_weight_by_bucket is not None and band_mass_raw > 0.0:
            age_mean = math.fsum(
                float(age_weight_by_bucket.get(bucket, 0.0))
                for bucket in range(lower, upper + 1)
            ) / band_mass_raw
        lower_price = float(price_for_bucket(lower))
        upper_price = float(price_for_bucket(upper))
        bounded.append(
            replace(
                peak,
                lower_bucket=lower,
                lower_price=lower_price,
                upper_bucket=upper,
                upper_price=upper_price,
                mass=band_mass,
                width_pct=upper_price / lower_price - 1.0,
                age_mean=age_mean,
            )
        )
    return tuple(bounded)


def dominant_canonical_peak(
    peaks: Iterable[CanonicalPeak],
) -> CanonicalPeak | None:
    """Select today's dominant peak with a stable lower-price tie break."""

    candidates = tuple(peaks)
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda peak: (
            round(peak.mass, 12),
            round(peak.prominence, 12),
            -peak.center_bucket,
        ),
    )


class TemporalPeakTracker:
    """Causally match canonical peaks; missing/ambiguous base identity fails closed."""

    def __init__(self, *, symbol: str, model: str) -> None:
        self._symbol = symbol
        self._model = model
        self._previous: tuple[TrackedPeak, ...] = ()
        self._base_track_id: str | None = None
        self._applied_action_ids: set[str] = set()

    def apply_corporate_action(
        self,
        *,
        action_id: str,
        cash_per_share: float = 0.0,
        share_multiplier: float = 1.0,
    ) -> None:
        """Move prior tracks onto the same ex-date coordinate exactly once."""

        if not action_id:
            raise ValueError("peak action id cannot be empty")
        if action_id in self._applied_action_ids:
            return
        self._previous = tuple(
            replace(
                peak,
                band=(
                    rebase_economic_price(
                        peak.band[0],
                        cash_per_share=cash_per_share,
                        share_multiplier=share_multiplier,
                    ),
                    rebase_economic_price(
                        peak.band[1],
                        cash_per_share=cash_per_share,
                        share_multiplier=share_multiplier,
                    ),
                ),
                center_price=rebase_economic_price(
                    peak.center_price,
                    cash_per_share=cash_per_share,
                    share_multiplier=share_multiplier,
                ),
            )
            for peak in self._previous
        )
        self._applied_action_ids.add(action_id)

    def update(self, *, as_of: date, candidates: tuple[CanonicalPeak, ...]) -> PeakTrackingResult:
        compatibility: dict[tuple[int, int], float] = {}
        for old_index, old in enumerate(self._previous):
            for new_index, new in enumerate(candidates):
                score = _match_score(old, new)
                if score is not None:
                    compatibility[(old_index, new_index)] = score

        old_options = {
            old_index: sorted(
                (
                    (score, new_index)
                    for (candidate_old, new_index), score in compatibility.items()
                    if candidate_old == old_index
                ),
                reverse=True,
            )
            for old_index in range(len(self._previous))
        }
        new_options = {
            new_index: sorted(
                (
                    (score, old_index)
                    for (old_index, candidate_new), score in compatibility.items()
                    if candidate_new == new_index
                ),
                reverse=True,
            )
            for new_index in range(len(candidates))
        }
        claimed_new: set[int] = set()
        observations: list[TrackedPeak] = []
        lost: list[TrackedPeak] = []
        for old_index, old in enumerate(self._previous):
            options = old_options[old_index]
            if not options:
                lost.append(replace(old, lost=True, ambiguity=True))
                continue
            score, new_index = options[0]
            split = len(options) > 1
            merge = len(new_options[new_index]) > 1
            tie = len(options) > 1 and abs(score - options[1][0]) <= 0.05
            ambiguous = split or merge or tie or new_index in claimed_new
            if new_index in claimed_new:
                lost.append(replace(old, lost=True, ambiguity=True, merge=True))
                continue
            claimed_new.add(new_index)
            new = candidates[new_index]
            observations.append(
                TrackedPeak(
                    peak_track_id=old.peak_track_id,
                    age=old.age + 1,
                    band=(new.lower_price, new.upper_price),
                    center_price=new.center_price,
                    mass=new.mass,
                    prominence=new.prominence,
                    ambiguity=ambiguous,
                    split=split,
                    merge=merge,
                    lost=False,
                    definition_version=new.definition_version,
                )
            )
        for new_index, new in enumerate(candidates):
            if new_index in claimed_new:
                continue
            observations.append(
                TrackedPeak(
                    peak_track_id=_new_track_id(self._symbol, self._model, as_of, new),
                    age=1,
                    band=(new.lower_price, new.upper_price),
                    center_price=new.center_price,
                    mass=new.mass,
                    prominence=new.prominence,
                    ambiguity=bool(new_options[new_index]),
                    split=False,
                    merge=bool(new_options[new_index]),
                    lost=False,
                    definition_version=new.definition_version,
                )
            )
        observations.sort(key=lambda peak: peak.center_price)
        dominant = max(
            observations,
            key=lambda peak: (
                round(peak.mass, 12),
                round(peak.prominence, 12),
                -peak.center_price,
            ),
            default=None,
        )
        if dominant is not None:
            runners_up = [peak for peak in observations if peak is not dominant]
            dominance_margin = dominant.mass - max(
                (peak.mass for peak in runners_up), default=-math.inf
            )
            if runners_up and round(dominance_margin, 12) < _DOMINANCE_AMBIGUITY_MASS:
                dominant = replace(dominant, ambiguity=True)
                observations = [
                    dominant if peak.peak_track_id == dominant.peak_track_id else peak
                    for peak in observations
                ]
        if self._base_track_id is None and dominant is not None and not dominant.ambiguity:
            self._base_track_id = dominant.peak_track_id
        tracked_base = next(
            (
                peak
                for peak in observations
                if peak.peak_track_id == self._base_track_id and not peak.ambiguity
            ),
            None,
        )
        reason: str | None = None
        if not observations:
            reason = "PEAK_MISSING"
        elif self._base_track_id is None:
            reason = "DOMINANT_PEAK_AMBIGUOUS"
        elif tracked_base is None:
            reason = "TRACKED_BASE_PEAK_LOST_OR_AMBIGUOUS"
        # Lost tracks are carried in the result as explicit terminal events,
        # but never become tomorrow's matching source.  A later look-alike is
        # necessarily a new identity rather than an unsafe reattachment.
        self._previous = tuple(observations)
        return PeakTrackingResult(
            peaks=tuple((*self._previous, *lost)),
            dominant_peak_today=dominant,
            tracked_base_peak=tracked_base,
            fail_closed_reason=reason,
        )


def _match_score(old: TrackedPeak, new: CanonicalPeak) -> float | None:
    old_lower, old_upper = old.band
    overlap = max(0.0, min(old_upper, new.upper_price) - max(old_lower, new.lower_price))
    union = max(old_upper, new.upper_price) - min(old_lower, new.lower_price)
    iou = overlap / union if union > 0.0 else 0.0
    log_distance = abs(math.log(new.center_price / old.center_price))
    permitted = max(0.03, math.log1p(max(new.width_pct, old_upper / old_lower - 1.0)))
    # Non-overlapping bands receive only a narrow continuity allowance.  A
    # larger action-day move must have been handled by the explicit coordinate
    # rebase; otherwise treating a nearby mode as the same identity is unsafe.
    if iou <= 0.0 and log_distance > 0.01:
        return None
    return 2.0 * iou - log_distance / permitted


def _new_track_id(symbol: str, model: str, as_of: date, peak: CanonicalPeak) -> str:
    payload = "|".join(
        (
            PEAK_TRACK_VERSION,
            symbol,
            model,
            as_of.isoformat(),
            str(peak.center_bucket),
            str(peak.lower_bucket),
            str(peak.upper_bucket),
        )
    )
    return f"peak-{sha256(payload.encode()).hexdigest()[:20]}"


class EnsembleTemporalPeakTracker:
    """Require a one-to-one peak match across every seller model before tracking.

    Local trackers preserve each seller model's causal daily identities.  The
    separate ensemble tracker only sees consensus candidates, so its id never
    means a concatenation of unrelated model-local ids.
    """

    def __init__(self, *, symbol: str, models: Iterable[str]) -> None:
        ordered = tuple(sorted(set(models)))
        if len(ordered) < 2:
            raise ValueError("ensemble peak tracking requires at least two seller models")
        self._models = ordered
        self._local = {
            model: TemporalPeakTracker(symbol=symbol, model=model) for model in ordered
        }
        self._ensemble = TemporalPeakTracker(symbol=symbol, model="ENSEMBLE")

    def apply_corporate_action(
        self,
        *,
        action_id: str,
        cash_per_share: float = 0.0,
        share_multiplier: float = 1.0,
    ) -> None:
        for tracker in (*self._local.values(), self._ensemble):
            tracker.apply_corporate_action(
                action_id=action_id,
                cash_per_share=cash_per_share,
                share_multiplier=share_multiplier,
            )

    def update(
        self,
        *,
        as_of: date,
        candidates_by_model: Mapping[str, tuple[CanonicalPeak, ...]],
    ) -> EnsemblePeakTrackingResult:
        if set(candidates_by_model) != set(self._models):
            empty = self._ensemble.update(as_of=as_of, candidates=())
            return EnsemblePeakTrackingResult(
                ensemble=replace(
                    empty,
                    tracked_base_peak=None,
                    fail_closed_reason="ENSEMBLE_SELLER_MODEL_MISSING",
                ),
                by_model={},
            )
        local = {
            model: self._local[model].update(
                as_of=as_of, candidates=tuple(candidates_by_model[model])
            )
            for model in self._models
        }
        candidates, ambiguous = _ensemble_candidates(
            candidates_by_model, self._models, as_of
        )
        ensemble = self._ensemble.update(as_of=as_of, candidates=candidates)
        if ambiguous:
            ensemble = replace(
                ensemble,
                tracked_base_peak=None,
                fail_closed_reason="ENSEMBLE_PEAK_AMBIGUOUS",
            )
        return EnsemblePeakTrackingResult(ensemble=ensemble, by_model=local)


def _ensemble_candidates(
    candidates_by_model: Mapping[str, tuple[CanonicalPeak, ...]],
    models: tuple[str, ...],
    as_of: date,
) -> tuple[tuple[CanonicalPeak, ...], bool]:
    """Build strictly one-to-one same-day seller-model peak consensus groups."""

    anchor_model = models[0]
    proposals: list[tuple[int, tuple[int, ...]]] = []
    ambiguous = False
    for anchor_index, anchor in enumerate(candidates_by_model[anchor_model]):
        selected = [anchor_index]
        for model in models[1:]:
            scored = sorted(
                (
                    (score, index)
                    for index, candidate in enumerate(candidates_by_model[model])
                    if (score := _canonical_match_score(anchor, candidate)) is not None
                ),
                reverse=True,
            )
            if not scored:
                selected = []
                break
            if len(scored) > 1 and abs(scored[0][0] - scored[1][0]) <= 0.05:
                ambiguous = True
                selected = []
                break
            selected.append(scored[0][1])
        if selected:
            proposals.append((anchor_index, tuple(selected)))

    for model_offset in range(1, len(models)):
        counts: dict[int, int] = {}
        for _, selected in proposals:
            index = selected[model_offset]
            counts[index] = counts.get(index, 0) + 1
        if any(count > 1 for count in counts.values()):
            ambiguous = True

    consensus: list[CanonicalPeak] = []
    for _, selected in proposals:
        if any(
            sum(other[1][offset] == selected[offset] for other in proposals) > 1
            for offset in range(1, len(models))
        ):
            continue
        grouped = [
            candidates_by_model[model][index]
            for model, index in zip(models, selected, strict=True)
        ]
        consensus.append(
            CanonicalPeak(
                center_bucket=round(median(peak.center_bucket for peak in grouped)),
                center_price=median(peak.center_price for peak in grouped),
                lower_bucket=round(median(peak.lower_bucket for peak in grouped)),
                lower_price=median(peak.lower_price for peak in grouped),
                upper_bucket=round(median(peak.upper_bucket for peak in grouped)),
                upper_price=median(peak.upper_price for peak in grouped),
                mass=median(peak.mass for peak in grouped),
                prominence=median(peak.prominence for peak in grouped),
                width_pct=median(peak.width_pct for peak in grouped),
                age_mean=None,
                formation_date=as_of.isoformat(),
            )
        )
    if len(consensus) != len(candidates_by_model[anchor_model]):
        ambiguous = True
    return tuple(sorted(consensus, key=lambda peak: peak.center_price)), ambiguous


def _canonical_match_score(left: CanonicalPeak, right: CanonicalPeak) -> float | None:
    synthetic = TrackedPeak(
        peak_track_id="candidate",
        age=0,
        band=(left.lower_price, left.upper_price),
        center_price=left.center_price,
        mass=left.mass,
        prominence=left.prominence,
        ambiguity=False,
        split=False,
        merge=False,
        lost=False,
        definition_version=left.definition_version,
    )
    return _match_score(synthetic, right)
