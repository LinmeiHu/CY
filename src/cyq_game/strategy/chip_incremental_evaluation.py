"""Preregistered transforms and evidence gates for chip incremental value."""

from __future__ import annotations

import hashlib
import math
from bisect import bisect_right
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime
from statistics import fmean
from typing import Any

import numpy as np

MODULES: dict[str, tuple[tuple[str, str], ...]] = {
    "concentrated_support": (
        ("i70_width_atr", "LOWER"),
        ("i90_width_atr", "LOWER"),
        ("dominant_band_mass", "HIGHER"),
    ),
    "cost_migration": (
        ("price_minus_cost_migration_20_vol", "HIGHER"),
        ("profit_ratio_change_20", "HIGHER"),
        ("i90_contraction_20", "HIGHER"),
    ),
    "overhead_resolution": (
        ("profit_ratio", "HIGHER"),
        ("upper_to_lower_peak_strength", "LOWER"),
        ("valley_depth", "HIGHER"),
    ),
}

COVARIATES = (
    "momentum_20",
    "atr_fraction",
    "turnover_fraction",
    "amount_mean20",
    "prior_breakout_excess_atr",
)


@dataclass(frozen=True)
class ForwardFold:
    fold_id: str
    fit_start: date
    fit_end: date
    evaluate_start: date
    evaluate_end: date


FORWARD_FOLDS = (
    ForwardFold(
        "FIT_2020_EVALUATE_2021",
        date(2020, 1, 2),
        date(2020, 12, 3),
        date(2021, 1, 4),
        date(2021, 12, 3),
    ),
    ForwardFold(
        "FIT_2020_2021_EVALUATE_2022",
        date(2020, 1, 2),
        date(2021, 12, 2),
        date(2022, 1, 4),
        date(2022, 12, 2),
    ),
)


@dataclass(frozen=True)
class ModuleTransform:
    fold: ForwardFold
    module: str
    disagreement_ceiling: float
    primitive_training_values: dict[str, tuple[float, ...]]
    covariate_training_values: dict[str, tuple[float, ...]]
    module_quintile_cutpoints: tuple[float, float, float, float]
    fit_rows: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def fit_module_transform(
    rows: Sequence[Mapping[str, Any]], module: str, fold: ForwardFold
) -> ModuleTransform:
    """Fit only measurement ECDFs and quality cutoffs, never outcome weights."""
    primitives = _module(module)
    fit = [
        row
        for row in rows
        if fold.fit_start <= _date(row["trade_date"]) <= fold.fit_end
        and row.get("chip_measurement_valid") is True
        and _number(row.get("seller_model_disagreement_atr")) is not None
    ]
    if not fit:
        raise ValueError(f"{fold.fold_id} has no measurable fit rows")
    disagreement = sorted(
        float(row["seller_model_disagreement_atr"]) for row in fit
    )
    ceiling = _quantile(disagreement, 0.80)
    eligible = [
        row for row in fit if float(row["seller_model_disagreement_atr"]) <= ceiling
    ]
    primitive_values = {
        name: _sorted_required(eligible, name) for name, _ in primitives
    }
    covariate_values = {
        name: _sorted_required(_with_covariates(eligible), name) for name in COVARIATES
    }
    scores = [
        _module_score(row, primitives, primitive_values, stale=False)
        for row in eligible
    ]
    if any(score is None for score in scores):
        raise ValueError("fit cohort has missing fixed module primitives")
    known_scores = sorted(float(score) for score in scores if score is not None)
    cutpoints = tuple(_quantile(known_scores, value) for value in (0.2, 0.4, 0.6, 0.8))
    return ModuleTransform(
        fold=fold,
        module=module,
        disagreement_ceiling=ceiling,
        primitive_training_values=primitive_values,
        covariate_training_values=covariate_values,
        module_quintile_cutpoints=(cutpoints[0], cutpoints[1], cutpoints[2], cutpoints[3]),
        fit_rows=len(eligible),
    )


def score_evaluation_rows(
    rows: Sequence[Mapping[str, Any]], transform: ModuleTransform
) -> list[dict[str, Any]]:
    primitives = _module(transform.module)
    scored: list[dict[str, Any]] = []
    for raw in rows:
        trade_date = _date(raw["trade_date"])
        if not transform.fold.evaluate_start <= trade_date <= transform.fold.evaluate_end:
            continue
        if raw.get("chip_measurement_valid") is not True:
            continue
        disagreement = _number(raw.get("seller_model_disagreement_atr"))
        if disagreement is None or disagreement > transform.disagreement_ceiling:
            continue
        row = _covariate_row(raw)
        current = _module_score(
            row,
            primitives,
            transform.primitive_training_values,
            stale=False,
        )
        stale = _module_score(
            row,
            primitives,
            transform.primitive_training_values,
            stale=True,
        )
        if current is None or stale is None:
            continue
        primitive_goodness = {
            name: _good_percentile(
                float(row[name]),
                transform.primitive_training_values[name],
                direction,
            )
            for name, direction in primitives
        }
        covariate_percentiles = {
            name: _percentile(
                float(row[name]), transform.covariate_training_values[name]
            )
            for name in COVARIATES
        }
        scored.append(
            {
                **dict(raw),
                "fold_id": transform.fold.fold_id,
                "module": transform.module,
                "module_score": current,
                "module_quintile": _quintile(
                    current, transform.module_quintile_cutpoints
                ),
                "stale_module_score": stale,
                "stale_module_quintile": _quintile(
                    stale, transform.module_quintile_cutpoints
                ),
                "module_quintile_cutpoints": transform.module_quintile_cutpoints,
                **{
                    f"goodness_{name}": value
                    for name, value in primitive_goodness.items()
                },
                **{
                    f"covariate_percentile_{name}": value
                    for name, value in covariate_percentiles.items()
                },
            }
        )
    return scored


def module_evidence(
    rows: Sequence[Mapping[str, Any]],
    module: str,
    *,
    protocol_event_id: str,
    bootstrap_resamples: int = 10_000,
    placebo_permutations: int = 199,
) -> dict[str, Any]:
    """Evaluate all fixed gates except the cross-module Holm correction."""
    primitives = _module(module)
    closed = [
        dict(row)
        for row in rows
        if row.get("module") == module
        and row.get("outcome_status") == "FILLED"
        and _number(row.get("return_fraction")) is not None
    ]
    top = [float(row["return_fraction"]) for row in closed if row["module_quintile"] == 5]
    bottom = [
        float(row["return_fraction"]) for row in closed if row["module_quintile"] == 1
    ]
    if not top or not bottom:
        return _insufficient(module, "EMPTY_PRIMARY_QUINTILE", len(closed))
    real_difference = _trimmed_mean(top) - _trimmed_mean(bottom)
    lower, upper = _weekly_cluster_bootstrap(
        closed,
        quintile_field="module_quintile",
        resamples=bootstrap_resamples,
        seed=_seed(f"{protocol_event_id}|{module}|BOOTSTRAP"),
    )
    half_width = (upper - lower) / 2.0
    weeks = {_week(row) for row in closed if row["module_quintile"] in {1, 5}}
    fold_differences: dict[str, float | None] = {}
    fold_weeks: dict[str, int] = {}
    for fold in FORWARD_FOLDS:
        subset = [row for row in closed if row["fold_id"] == fold.fold_id]
        fold_top = [
            float(row["return_fraction"])
            for row in subset
            if row["module_quintile"] == 5
        ]
        fold_bottom = [
            float(row["return_fraction"])
            for row in subset
            if row["module_quintile"] == 1
        ]
        fold_differences[fold.fold_id] = (
            _trimmed_mean(fold_top) - _trimmed_mean(fold_bottom)
            if fold_top and fold_bottom
            else None
        )
        fold_weeks[fold.fold_id] = len(
            {_week(row) for row in subset if row["module_quintile"] in {1, 5}}
        )
    quintile_returns = {
        str(quintile): _trimmed_mean(
            [
                float(row["return_fraction"])
                for row in closed
                if row["module_quintile"] == quintile
            ]
        )
        for quintile in range(1, 6)
    }
    adjacent = [
        quintile_returns[str(right)] - quintile_returns[str(right - 1)]
        for right in range(2, 6)
    ]
    monotone_steps = sum(value >= 0 for value in adjacent)
    primitive_differences: dict[str, float | None] = {}
    for name, _ in primitives:
        high = [
            float(row["return_fraction"])
            for row in closed
            if float(row[f"goodness_{name}"]) >= 0.8
        ]
        low = [
            float(row["return_fraction"])
            for row in closed
            if float(row[f"goodness_{name}"]) <= 0.2
        ]
        primitive_differences[name] = (
            _trimmed_mean(high) - _trimmed_mean(low) if high and low else None
        )
    primitive_passes = sum(
        value is not None and value > 0 for value in primitive_differences.values()
    )
    stale_top = [
        float(row["return_fraction"])
        for row in closed
        if row["stale_module_quintile"] == 5
    ]
    stale_bottom = [
        float(row["return_fraction"])
        for row in closed
        if row["stale_module_quintile"] == 1
    ]
    stale_difference = (
        _trimmed_mean(stale_top) - _trimmed_mean(stale_bottom)
        if stale_top and stale_bottom
        else None
    )
    placebo, placebo_support = _placebo_statistics(
        closed,
        module,
        protocol_event_id=protocol_event_id,
        permutations=placebo_permutations,
    )
    placebo_99 = _quantile(sorted(placebo), 0.99)
    empirical_p = (1 + sum(value >= real_difference for value in placebo)) / (
        len(placebo) + 1
    )
    observed_icc = _weekly_icc(
        [row for row in closed if row["module_quintile"] in {1, 5}]
    )
    n_primary = len(top) + len(bottom)
    mean_cluster = n_primary / max(len(weeks), 1)
    effective_sample = n_primary / (
        1.0 + max(mean_cluster - 1.0, 0.0) * max(observed_icc, 0.10)
    )
    gates = {
        "effect_at_least_one_percent": real_difference >= 0.01,
        "lower_95_positive": lower > 0,
        "ci_half_width_at_most_one_percent": half_width <= 0.01,
        "combined_weeks_at_least_52": len(weeks) >= 52,
        "each_fold_weeks_at_least_20": all(value >= 20 for value in fold_weeks.values()),
        "effective_sample_at_least_396": effective_sample >= 396,
        "both_fold_differences_positive": all(
            value is not None and value > 0 for value in fold_differences.values()
        ),
        "minimum_three_monotone_steps": monotone_steps >= 3,
        "maximum_adverse_reversal": min(adjacent) >= -0.0025,
        "at_least_two_directional_primitives": primitive_passes >= 2,
        "current_stronger_than_stale": (
            stale_difference is not None and real_difference > stale_difference
        ),
        "real_exceeds_placebo_99": real_difference > placebo_99,
        "informative_swappable_rows_at_least_396": (
            placebo_support["informative_rows"] >= 396
        ),
        "informative_weeks_at_least_52": (
            placebo_support["informative_weeks"] >= 52
        ),
        "each_fold_informative_weeks_at_least_20": all(
            value >= 20
            for value in placebo_support["informative_fold_weeks"].values()
        ),
    }
    identifiable = all(
        gates[name]
        for name in (
            "informative_swappable_rows_at_least_396",
            "informative_weeks_at_least_52",
            "each_fold_informative_weeks_at_least_20",
        )
    )
    return {
        "module": module,
        "status_before_holm": (
            "PASS"
            if all(gates.values())
            else "FAIL"
            if identifiable
            else "INSUFFICIENT_EVIDENCE"
        ),
        "closed_rows": len(closed),
        "primary_top_rows": len(top),
        "primary_bottom_rows": len(bottom),
        "trimmed_mean_difference": real_difference,
        "weekly_cluster_bootstrap_95": [lower, upper],
        "ci_half_width": half_width,
        "distinct_signal_weeks": len(weeks),
        "fold_weeks": fold_weeks,
        "fold_differences": fold_differences,
        "quintile_trimmed_returns": quintile_returns,
        "adjacent_differences": adjacent,
        "monotone_adjacent_steps": monotone_steps,
        "primitive_differences": primitive_differences,
        "directional_primitive_passes": primitive_passes,
        "stale_trimmed_mean_difference": stale_difference,
        "observed_weekly_icc": observed_icc,
        "effective_sample": effective_sample,
        "placebo_permutations": len(placebo),
        "placebo_99_quantile": placebo_99,
        "placebo_empirical_p": empirical_p,
        "placebo_swappable_rows": placebo_support["swappable_rows"],
        "placebo_swappable_ratio": (
            placebo_support["swappable_rows"] / len(closed)
        ),
        "placebo_informative_pairs": placebo_support["informative_pairs"],
        "placebo_informative_rows": placebo_support["informative_rows"],
        "placebo_informative_weeks": placebo_support["informative_weeks"],
        "placebo_informative_fold_weeks": placebo_support[
            "informative_fold_weeks"
        ],
        "gates": gates,
    }


def apply_holm(evidence: Sequence[Mapping[str, Any]], alpha: float = 0.05) -> dict[str, bool]:
    ordered = sorted(
        (
            (str(item["module"]), float(item.get("placebo_empirical_p", 1.0)))
            for item in evidence
        ),
        key=lambda item: (item[1], item[0]),
    )
    result = {module: False for module, _ in ordered}
    for index, (module, p_value) in enumerate(ordered):
        threshold = alpha / (len(ordered) - index)
        if p_value > threshold:
            break
        result[module] = True
    return result


def _module_score(
    row: Mapping[str, Any],
    primitives: Sequence[tuple[str, str]],
    training: Mapping[str, tuple[float, ...]],
    *,
    stale: bool,
) -> float | None:
    values: list[float] = []
    for name, direction in primitives:
        field = f"stale_{name}" if stale else name
        value = _number(row.get(field))
        if value is None:
            return None
        values.append(_good_percentile(value, training[name], direction))
    return fmean(values)


def _good_percentile(value: float, training: tuple[float, ...], direction: str) -> float:
    percentile = _percentile(value, training)
    if direction == "HIGHER":
        return percentile
    if direction == "LOWER":
        return 1.0 - percentile
    raise ValueError(f"unknown primitive direction: {direction}")


def _percentile(value: float, training: tuple[float, ...]) -> float:
    return bisect_right(training, value) / len(training)


def _quintile(value: float, cutpoints: Sequence[float]) -> int:
    return bisect_right(tuple(cutpoints), value) + 1


def _placebo_statistics(
    rows: list[dict[str, Any]],
    module: str,
    *,
    protocol_event_id: str,
    permutations: int,
) -> tuple[list[float], dict[str, Any]]:
    pairs = _restricted_pairs(rows)
    base_scores = [float(row["module_score"]) for row in rows]
    informative_pairs: list[tuple[str, int, int]] = []
    for pair in pairs:
        _, left, right = pair
        before_left = int(rows[left]["module_quintile"])
        before_right = int(rows[right]["module_quintile"])
        after_left = _quintile(
            base_scores[right], rows[left]["module_quintile_cutpoints"]
        )
        after_right = _quintile(
            base_scores[left], rows[right]["module_quintile_cutpoints"]
        )
        if (
            before_left != after_left
            and {before_left, after_left}.intersection({1, 5})
        ) or (
            before_right != after_right
            and {before_right, after_right}.intersection({1, 5})
        ):
            informative_pairs.append(pair)
    statistics: list[float] = []
    for permutation in range(permutations):
        scores = base_scores.copy()
        for pair_id, left, right in pairs:
            value = f"{protocol_event_id}|{module}|{permutation}|{pair_id}"
            if hashlib.sha256(value.encode()).digest()[0] & 1:
                scores[left], scores[right] = scores[right], scores[left]
        top: list[float] = []
        bottom: list[float] = []
        for index, row in enumerate(rows):
            quintile = _quintile(scores[index], row["module_quintile_cutpoints"])
            if quintile == 5:
                top.append(float(row["return_fraction"]))
            elif quintile == 1:
                bottom.append(float(row["return_fraction"]))
        statistics.append(
            _trimmed_mean(top) - _trimmed_mean(bottom)
            if top and bottom
            else 0.0
        )
    swappable_indices = {index for _, left, right in pairs for index in (left, right)}
    informative_indices = {
        index for _, left, right in informative_pairs for index in (left, right)
    }
    informative_fold_weeks = {
        fold.fold_id: len(
            {
                _week(rows[index])
                for index in informative_indices
                if rows[index]["fold_id"] == fold.fold_id
            }
        )
        for fold in FORWARD_FOLDS
    }
    return statistics, {
        "swappable_rows": len(swappable_indices),
        "informative_pairs": len(informative_pairs),
        "informative_rows": len(informative_indices),
        "informative_weeks": len({_week(rows[index]) for index in informative_indices}),
        "informative_fold_weeks": informative_fold_weeks,
    }


def _restricted_pairs(rows: Sequence[Mapping[str, Any]]) -> list[tuple[str, int, int]]:
    groups: defaultdict[tuple[Any, ...], list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        groups[
            (
                row["fold_id"],
                _week(row),
                str(row["industry"]),
                str(row["market_state"]),
                str(row["sector_state"]),
            )
        ].append(index)
    pairs: list[tuple[str, int, int]] = []
    for _key, indices in sorted(groups.items(), key=lambda item: str(item[0])):
        remaining = sorted(indices, key=lambda index: str(rows[index]["candidate_id"]))
        while len(remaining) >= 2:
            candidates: list[tuple[float, str, int, int]] = []
            for left_position, left in enumerate(remaining[:-1]):
                for right in remaining[left_position + 1 :]:
                    distance = math.fsum(
                        abs(
                            float(rows[left][f"covariate_percentile_{name}"])
                            - float(rows[right][f"covariate_percentile_{name}"])
                        )
                        for name in COVARIATES
                    )
                    pair_key = "|".join(
                        sorted(
                            (
                                str(rows[left]["candidate_id"]),
                                str(rows[right]["candidate_id"]),
                            )
                        )
                    )
                    candidates.append((distance, pair_key, left, right))
            distance, pair_key, left, right = min(candidates)
            if distance > 1.0:
                break
            fold_id = str(rows[left]["fold_id"])
            pairs.append((f"{fold_id}|{pair_key}", left, right))
            remaining.remove(left)
            remaining.remove(right)
    return pairs


def _weekly_cluster_bootstrap(
    rows: Sequence[Mapping[str, Any]],
    *,
    quintile_field: str,
    resamples: int,
    seed: int,
) -> tuple[float, float]:
    by_week: defaultdict[tuple[int, int], list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        if int(row[quintile_field]) in {1, 5}:
            by_week[_week(row)].append(row)
    weeks = sorted(by_week)
    if len(weeks) < 2:
        raise ValueError("weekly cluster bootstrap requires at least two weeks")
    rng = np.random.default_rng(seed)
    values = np.empty(resamples, dtype=np.float64)
    for index in range(resamples):
        selected = rng.integers(0, len(weeks), size=len(weeks))
        top: list[float] = []
        bottom: list[float] = []
        for raw in selected:
            for row in by_week[weeks[int(raw)]]:
                target = top if int(row[quintile_field]) == 5 else bottom
                target.append(float(row["return_fraction"]))
        values[index] = _trimmed_mean(top) - _trimmed_mean(bottom)
    return float(np.quantile(values, 0.025)), float(np.quantile(values, 0.975))


def _weekly_icc(rows: Sequence[Mapping[str, Any]]) -> float:
    groups: defaultdict[tuple[int, int], list[float]] = defaultdict(list)
    for row in rows:
        groups[_week(row)].append(float(row["return_fraction"]))
    if len(groups) < 2:
        return 1.0
    means = [fmean(values) for values in groups.values()]
    within_numerator = math.fsum(
        math.fsum((value - fmean(values)) ** 2 for value in values)
        for values in groups.values()
    )
    within_denominator = sum(max(len(values) - 1, 0) for values in groups.values())
    within = within_numerator / within_denominator if within_denominator else 0.0
    between = float(np.var(means, ddof=1))
    mean_size = fmean(len(values) for values in groups.values())
    signal = max(between - within / max(mean_size, 1.0), 0.0)
    return signal / (signal + within) if signal + within > 0 else 0.0


def _trimmed_mean(values: Sequence[float], proportion: float = 0.05) -> float:
    if not values:
        return float("nan")
    ordered = sorted(float(value) for value in values)
    trim = int(len(ordered) * proportion)
    selected = ordered[trim : len(ordered) - trim] if trim else ordered
    return fmean(selected)


def _with_covariates(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [_covariate_row(row) for row in rows]


def _covariate_row(row: Mapping[str, Any]) -> dict[str, Any]:
    close = _number(row.get("close"))
    atr = _number(row.get("atr14"))
    result = dict(row)
    result["atr_fraction"] = (
        atr / close if atr is not None and close is not None and close > 0 else None
    )
    return result


def _sorted_required(rows: Sequence[Mapping[str, Any]], name: str) -> tuple[float, ...]:
    values = [_number(row.get(name)) for row in rows]
    if not values or any(value is None for value in values):
        raise ValueError(f"training field {name} is missing or non-finite")
    return tuple(sorted(float(value) for value in values if value is not None))


def _quantile(values: Sequence[float], probability: float) -> float:
    if not values:
        raise ValueError("quantile requires values")
    return float(np.quantile(np.asarray(values, dtype=np.float64), probability))


def _week(row: Mapping[str, Any]) -> tuple[int, int]:
    iso = _date(row["trade_date"]).isocalendar()
    return iso.year, iso.week


def _module(name: str) -> tuple[tuple[str, str], ...]:
    try:
        return MODULES[name]
    except KeyError as error:
        raise ValueError(f"unknown chip hypothesis module: {name}") from error


def _number(value: object) -> float | None:
    if value is None:
        return None
    parsed = float(value)  # type: ignore[arg-type]
    return parsed if math.isfinite(parsed) else None


def _date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _seed(value: str) -> int:
    return int.from_bytes(hashlib.sha256(value.encode()).digest()[:8], "big")


def _insufficient(module: str, reason: str, rows: int) -> dict[str, Any]:
    return {
        "module": module,
        "status_before_holm": "INSUFFICIENT_EVIDENCE",
        "closed_rows": rows,
        "reason_codes": [reason],
        "placebo_empirical_p": 1.0,
        "gates": {},
    }
