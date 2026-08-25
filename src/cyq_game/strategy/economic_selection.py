"""Preregistered economic gates for the 81-point entry lattice."""

from __future__ import annotations

import hashlib
import math
from collections import defaultdict, deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from statistics import fmean
from typing import Any

import numpy as np

from cyq_game.strategy.markup_retest import StrategyParameters

ENTRY_DIMENSIONS = (
    "setup_score_min",
    "breakout_buffer_atr",
    "max_retest_depth_atr",
    "min_cost_migration_atr",
)


@dataclass(frozen=True)
class EconomicGateThresholds:
    minimum_entry_fill_rate: float = 0.95
    minimum_closed_trade_rate: float = 0.95
    minimum_distinct_signal_weeks: int = 104
    minimum_effective_sample: float = 396.0
    maximum_ci_half_width: float = 0.01
    profit_factor_minimum: float = 1.0
    portfolio_max_drawdown_fraction: float = 0.20
    blocked_tail_loss_ratio_maximum: float = 0.01
    one_percent_trade_cvar_floor: float = -0.25
    first_5m_participation_p95_maximum: float = 0.10
    first_5m_participation_absolute_maximum: float = 0.25


DEFAULT_ECONOMIC_GATE_THRESHOLDS = EconomicGateThresholds()


@dataclass(frozen=True)
class CandidateAssessment:
    parameter_id: str
    status: str
    base_gate_pass: bool
    reason_codes: tuple[str, ...]
    adjacent_parameter_ids: tuple[str, ...] = ()
    passing_adjacent_parameter_ids: tuple[str, ...] = ()
    adjacent_economic_passes: int = 0
    robust_region_eligible: bool = False


@dataclass(frozen=True)
class RobustRegionDecision:
    decision: str
    reason_codes: tuple[str, ...]
    passing_parameter_ids: tuple[str, ...]
    components: tuple[tuple[str, ...], ...]
    selected_component: tuple[str, ...]
    selected_parameter_id: str | None
    assessments: tuple[CandidateAssessment, ...]


def trimmed_mean(values: Sequence[float], trim_fraction: float = 0.05) -> float:
    if not values:
        raise ValueError("trimmed mean requires at least one value")
    if not 0.0 <= trim_fraction < 0.5:
        raise ValueError("trim fraction must be in [0, 0.5)")
    ordered = sorted(float(value) for value in values)
    trim = math.floor(len(ordered) * trim_fraction)
    kept = ordered[trim : len(ordered) - trim] if trim else ordered
    return fmean(kept)


def weekly_cluster_evidence(
    returns_by_week: Mapping[str, Sequence[float]],
    *,
    parameter_id: str,
    resamples: int = 10_000,
    icc_floor: float = 0.10,
) -> dict[str, float | int | None]:
    clusters = {
        str(week): tuple(float(value) for value in values)
        for week, values in returns_by_week.items()
        if values
    }
    flat = [value for values in clusters.values() for value in values]
    if not flat:
        return {
            "trade_count": 0,
            "distinct_signal_weeks": 0,
            "observed_icc": None,
            "effective_sample": 0.0,
            "bootstrap_lower_95": None,
            "bootstrap_upper_95": None,
            "bootstrap_half_width": None,
        }
    observed_icc = intracluster_correlation(tuple(clusters.values()))
    mean_cluster_size = len(flat) / len(clusters)
    effective = len(flat) / (
        1.0 + (mean_cluster_size - 1.0) * max(observed_icc, icc_floor)
    )
    weeks = tuple(sorted(clusters))
    seed = int.from_bytes(
        hashlib.sha256(
            f"{parameter_id}|ENTRY_ECONOMIC_SELECTION_V2".encode()
        ).digest()[:8],
        "big",
    )
    lower, upper = cluster_bootstrap_trimmed_interval(
        tuple(clusters[week] for week in weeks),
        resamples=resamples,
        seed=seed,
    )
    return {
        "trade_count": len(flat),
        "distinct_signal_weeks": len(clusters),
        "observed_icc": observed_icc,
        "effective_sample": effective,
        "bootstrap_lower_95": float(lower),
        "bootstrap_upper_95": float(upper),
        "bootstrap_half_width": float((upper - lower) / 2.0),
    }


def cluster_bootstrap_trimmed_interval(
    clusters: Sequence[Sequence[float]],
    *,
    resamples: int,
    seed: int,
    trim_fraction: float = 0.05,
    batch_size: int = 256,
) -> tuple[float, float]:
    """Vectorize the exact cluster-resample multiset and trimmed estimator."""

    nonempty = tuple(
        tuple(float(value) for value in cluster) for cluster in clusters if cluster
    )
    if not nonempty:
        raise ValueError("cluster bootstrap requires at least one nonempty cluster")
    if resamples < 1 or batch_size < 1:
        raise ValueError("cluster bootstrap resamples and batch size must be positive")
    if not 0.0 <= trim_fraction < 0.5:
        raise ValueError("trim fraction must be in [0, 0.5)")
    cluster_count = len(nonempty)
    ordered = sorted(
        (value, cluster_index)
        for cluster_index, cluster in enumerate(nonempty)
        for value in cluster
    )
    values = np.asarray([item[0] for item in ordered], dtype=np.float64)
    cluster_index_by_value = np.asarray(
        [item[1] for item in ordered], dtype=np.intp
    )
    cluster_sizes = np.asarray([len(item) for item in nonempty], dtype=np.int64)
    generator = np.random.default_rng(seed)
    estimates = np.empty(resamples, dtype=np.float64)
    for start in range(0, resamples, batch_size):
        size = min(batch_size, resamples - start)
        sampled = generator.integers(0, cluster_count, size=(size, cluster_count))
        counts = np.zeros((size, cluster_count), dtype=np.int32)
        np.add.at(
            counts,
            (np.repeat(np.arange(size), cluster_count), sampled.reshape(-1)),
            1,
        )
        weights = counts[:, cluster_index_by_value]
        totals = counts @ cluster_sizes
        trim = np.floor(totals * trim_fraction).astype(np.int64)
        total_sum = np.sum(weights * values, axis=1, dtype=np.float64)
        low_sum = _weighted_prefix_sum(weights, values, trim)
        high_sum = _weighted_prefix_sum(
            weights[:, ::-1], values[::-1], trim
        )
        estimates[start : start + size] = (
            total_sum - low_sum - high_sum
        ) / (totals - 2 * trim)
    lower, upper = np.quantile(estimates, (0.025, 0.975)).tolist()
    return float(lower), float(upper)


def _weighted_prefix_sum(
    weights: np.ndarray[Any, Any],
    values: np.ndarray[Any, Any],
    length: np.ndarray[Any, Any],
) -> np.ndarray[Any, Any]:
    result = np.zeros(weights.shape[0], dtype=np.float64)
    selected = length > 0
    if not np.any(selected):
        return result
    chosen_weights = weights[selected]
    chosen_length = length[selected]
    cumulative_count = np.cumsum(chosen_weights, axis=1)
    boundary = np.argmax(cumulative_count >= chosen_length[:, None], axis=1)
    row = np.arange(len(boundary))
    previous_count = np.where(
        boundary > 0,
        cumulative_count[row, np.maximum(boundary - 1, 0)],
        0,
    )
    cumulative_sum = np.cumsum(chosen_weights * values, axis=1, dtype=np.float64)
    previous_sum = np.where(
        boundary > 0,
        cumulative_sum[row, np.maximum(boundary - 1, 0)],
        0.0,
    )
    result[selected] = previous_sum + (
        chosen_length - previous_count
    ) * values[boundary]
    return result


def intracluster_correlation(clusters: Sequence[Sequence[float]]) -> float:
    nonempty = [tuple(float(value) for value in cluster) for cluster in clusters if cluster]
    count = sum(len(cluster) for cluster in nonempty)
    group_count = len(nonempty)
    if group_count < 2 or count <= group_count:
        return 0.0
    overall = fmean(value for cluster in nonempty for value in cluster)
    between = sum(
        len(cluster) * (fmean(cluster) - overall) ** 2 for cluster in nonempty
    ) / (group_count - 1)
    within = sum(
        sum((value - fmean(cluster)) ** 2 for value in cluster)
        for cluster in nonempty
    ) / (count - group_count)
    mean_size = (
        count - sum(len(cluster) ** 2 for cluster in nonempty) / count
    ) / (group_count - 1)
    denominator = between + (mean_size - 1.0) * within
    if denominator <= 0.0:
        return 0.0
    return max(-1.0, min(1.0, (between - within) / denominator))


def assess_candidate(
    parameter_id: str,
    metrics: Mapping[str, Any],
    *,
    thresholds: EconomicGateThresholds = DEFAULT_ECONOMIC_GATE_THRESHOLDS,
) -> CandidateAssessment:
    reasons: list[str] = []
    sample_reasons: list[str] = []
    if int(metrics["distinct_signal_weeks"]) < thresholds.minimum_distinct_signal_weeks:
        sample_reasons.append("DISTINCT_SIGNAL_WEEKS_BELOW_MINIMUM")
    if float(metrics["effective_sample"]) < thresholds.minimum_effective_sample:
        sample_reasons.append("EFFECTIVE_SAMPLE_BELOW_MINIMUM")
    half_width = metrics.get("bootstrap_half_width")
    if half_width is None or float(half_width) > thresholds.maximum_ci_half_width:
        sample_reasons.append("BOOTSTRAP_CI_TOO_WIDE")
    if sample_reasons:
        return CandidateAssessment(
            parameter_id=parameter_id,
            status="INSUFFICIENT_EVIDENCE",
            base_gate_pass=False,
            reason_codes=tuple(sample_reasons),
        )
    checks = (
        (
            float(metrics["entry_fill_rate"])
            >= thresholds.minimum_entry_fill_rate,
            "ENTRY_FILL_RATE_BELOW_MINIMUM",
        ),
        (
            float(metrics["closed_trade_rate"])
            >= thresholds.minimum_closed_trade_rate,
            "CLOSED_TRADE_RATE_BELOW_MINIMUM",
        ),
        (
            float(metrics["bootstrap_lower_95"]) > 0.0,
            "BOOTSTRAP_LOWER_95_NOT_POSITIVE",
        ),
        (
            float(metrics["baseline_difference_lower_95"]) > 0.0,
            "MATCHED_BASELINE_DIFFERENCE_LOWER_95_NOT_POSITIVE",
        ),
        (
            float(metrics["profit_factor"]) >= thresholds.profit_factor_minimum,
            "PROFIT_FACTOR_BELOW_MINIMUM",
        ),
        (
            abs(float(metrics["portfolio_max_drawdown_fraction"]))
            <= thresholds.portfolio_max_drawdown_fraction,
            "PORTFOLIO_MAX_DRAWDOWN_EXCEEDED",
        ),
        (
            float(metrics["blocked_tail_loss_ratio"])
            <= thresholds.blocked_tail_loss_ratio_maximum,
            "BLOCKED_TAIL_LOSS_RATIO_EXCEEDED",
        ),
        (
            float(metrics["trade_cvar_1pct"])
            >= thresholds.one_percent_trade_cvar_floor,
            "TRADE_CVAR_1PCT_BELOW_FLOOR",
        ),
        (
            float(metrics["first_5m_participation_p95"])
            <= thresholds.first_5m_participation_p95_maximum,
            "FIRST_5M_PARTICIPATION_P95_EXCEEDED",
        ),
        (
            float(metrics["first_5m_participation_max"])
            <= thresholds.first_5m_participation_absolute_maximum,
            "FIRST_5M_PARTICIPATION_ABSOLUTE_MAX_EXCEEDED",
        ),
        (
            int(metrics["maximum_concurrent_positions"]) <= 50,
            "MAXIMUM_CONCURRENT_POSITIONS_EXCEEDED",
        ),
        (
            int(metrics["maximum_concurrent_same_industry_positions"]) <= 10,
            "MAXIMUM_CONCURRENT_SAME_INDUSTRY_POSITIONS_EXCEEDED",
        ),
        (
            int(metrics["maximum_same_day_new_entries"]) <= 10,
            "MAXIMUM_SAME_DAY_NEW_ENTRIES_EXCEEDED",
        ),
    )
    reasons.extend(reason for passed, reason in checks if not passed)
    return CandidateAssessment(
        parameter_id=parameter_id,
        status="PASS" if not reasons else "FAIL",
        base_gate_pass=not reasons,
        reason_codes=tuple(reasons),
    )


def select_robust_region(
    parameters: Sequence[StrategyParameters],
    assessments: Sequence[CandidateAssessment],
    metrics_by_id: Mapping[str, Mapping[str, Any]],
    grids: Mapping[str, Sequence[float]],
) -> RobustRegionDecision:
    by_id = {assessment.parameter_id: assessment for assessment in assessments}
    parameter_by_id = {parameter.parameter_id: parameter for parameter in parameters}
    if set(by_id) != set(parameter_by_id):
        raise ValueError("every parameter must have exactly one economic assessment")
    neighbors = {
        parameter.parameter_id: tuple(
            sorted(
                other.parameter_id
                for other in parameters
                if _entry_neighbor(parameter, other, grids)
            )
        )
        for parameter in parameters
    }
    updated: dict[str, CandidateAssessment] = {}
    passing_ids = {item.parameter_id for item in assessments if item.base_gate_pass}
    for parameter_id, assessment in by_id.items():
        passing_neighbors = tuple(
            item for item in neighbors[parameter_id] if item in passing_ids
        )
        updated[parameter_id] = CandidateAssessment(
            parameter_id=parameter_id,
            status=assessment.status,
            base_gate_pass=assessment.base_gate_pass,
            reason_codes=assessment.reason_codes,
            adjacent_parameter_ids=neighbors[parameter_id],
            passing_adjacent_parameter_ids=passing_neighbors,
            adjacent_economic_passes=len(passing_neighbors),
            robust_region_eligible=assessment.base_gate_pass and bool(passing_neighbors),
        )
    components = _components(passing_ids, neighbors)
    eligible_components = tuple(component for component in components if len(component) >= 3)
    if not eligible_components:
        reason = (
            "INSUFFICIENT_EVIDENCE"
            if not passing_ids
            and all(item.status == "INSUFFICIENT_EVIDENCE" for item in assessments)
            else "NO_ROBUST_ENTRY_REGION"
        )
        return RobustRegionDecision(
            decision="NO_TRADE",
            reason_codes=(reason,),
            passing_parameter_ids=tuple(sorted(passing_ids)),
            components=components,
            selected_component=(),
            selected_parameter_id=None,
            assessments=tuple(updated[item.parameter_id] for item in assessments),
        )
    selected_component = sorted(
        eligible_components,
        key=lambda component: _component_key(component, metrics_by_id),
    )[0]
    selected_parameter = sorted(
        selected_component,
        key=lambda parameter_id: (
            _component_distance(parameter_id, selected_component, parameter_by_id, grids),
            parameter_id,
        ),
    )[0]
    return RobustRegionDecision(
        decision="PASS",
        reason_codes=(),
        passing_parameter_ids=tuple(sorted(passing_ids)),
        components=components,
        selected_component=selected_component,
        selected_parameter_id=selected_parameter,
        assessments=tuple(updated[item.parameter_id] for item in assessments),
    )


def _entry_neighbor(
    left: StrategyParameters,
    right: StrategyParameters,
    grids: Mapping[str, Sequence[float]],
) -> bool:
    distances = []
    for name in ENTRY_DIMENSIONS:
        values = tuple(float(value) for value in grids[name])
        distances.append(
            abs(values.index(getattr(left, name)) - values.index(getattr(right, name)))
        )
    return sum(distances) == 1


def _components(
    passing_ids: set[str],
    neighbors: Mapping[str, Sequence[str]],
) -> tuple[tuple[str, ...], ...]:
    remaining = set(passing_ids)
    result: list[tuple[str, ...]] = []
    while remaining:
        first = min(remaining)
        queue: deque[str] = deque((first,))
        component: set[str] = set()
        while queue:
            current = queue.popleft()
            if current in component:
                continue
            component.add(current)
            queue.extend(
                neighbor
                for neighbor in neighbors[current]
                if neighbor in passing_ids and neighbor not in component
            )
        remaining -= component
        result.append(tuple(sorted(component)))
    return tuple(sorted(result))


def _component_key(
    component: Sequence[str],
    metrics_by_id: Mapping[str, Mapping[str, Any]],
) -> tuple[float, float, float, tuple[str, ...]]:
    return (
        -min(float(metrics_by_id[item]["bootstrap_lower_95"]) for item in component),
        max(
            abs(float(metrics_by_id[item]["portfolio_max_drawdown_fraction"]))
            for item in component
        ),
        max(float(metrics_by_id[item]["blocked_tail_loss_ratio"]) for item in component),
        tuple(component),
    )


def _component_distance(
    parameter_id: str,
    component: Sequence[str],
    parameters: Mapping[str, StrategyParameters],
    grids: Mapping[str, Sequence[float]],
) -> int:
    origin = parameters[parameter_id]
    total = 0
    for other_id in component:
        other = parameters[other_id]
        for name in ENTRY_DIMENSIONS:
            values = tuple(float(value) for value in grids[name])
            total += abs(
                values.index(getattr(origin, name))
                - values.index(getattr(other, name))
            )
    return total


def group_returns_by_iso_week(
    trades: Sequence[Mapping[str, Any]],
) -> dict[str, tuple[float, ...]]:
    grouped: defaultdict[str, list[float]] = defaultdict(list)
    for trade in trades:
        signal_date = str(trade["signal_at"])[:10]
        year, week, _ = date.fromisoformat(signal_date).isocalendar()
        grouped[f"{year:04d}-W{week:02d}"].append(float(trade["return_fraction"]))
    return {key: tuple(values) for key, values in sorted(grouped.items())}
