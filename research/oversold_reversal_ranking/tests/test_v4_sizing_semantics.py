from __future__ import annotations

import math
from itertools import pairwise

from research.oversold_reversal_ranking import v3_risk_filter, v4_sizing


def test_v4_imports_the_exact_v3_score_builder() -> None:
    assert v4_sizing.create_risk_tables is v3_risk_filter.create_risk_tables


def test_primary_mapping_is_monotone_positive_and_exact_mean_one() -> None:
    counts = [4472, 4472, 4471, 4471, 4471]
    raw = [1.25, 1.125, 1.0, 0.875, 0.75]
    raw_mean = sum(n * weight for n, weight in zip(counts, raw, strict=True)) / sum(
        counts
    )
    normalized = [weight / raw_mean for weight in raw]
    assert all(weight > 0 for weight in normalized)
    assert all(left > right for left, right in pairwise(normalized))
    normalized_mean = sum(
        n * weight for n, weight in zip(counts, normalized, strict=True)
    ) / sum(counts)
    assert math.isclose(normalized_mean, 1.0, abs_tol=1e-15)


def test_conservative_mapping_is_not_normalized() -> None:
    counts = [4472, 4472, 4471, 4471, 4471]
    weights = [1.0, 0.95, 0.90, 0.80, 0.70]
    mean_weight = sum(
        n * weight for n, weight in zip(counts, weights, strict=True)
    ) / sum(counts)
    assert math.isclose(mean_weight, 0.8700093930312653)
    assert all(left > right for left, right in pairwise(weights))


def test_weighted_event_arithmetic_and_severe_labels_are_distinct() -> None:
    weight, ret_20, mae_20, mfe_20 = 0.75, 0.12, -0.12, 0.18
    assert math.isclose(weight * ret_20, 0.09)
    assert math.isclose(weight * mae_20, -0.09)
    assert math.isclose(weight * mfe_20, 0.135)
    assert mae_20 <= -0.10  # underlying severe path remains severe
    assert not (weight * mae_20 <= -0.10)  # capital loss is not severe at this size


def test_capital_contribution_reconciles_to_weighted_mean() -> None:
    weights = [1.25, 0.75]
    returns = [0.10, -0.02]
    contributions = [weight * ret / 2 for weight, ret in zip(weights, returns, strict=True)]
    weighted_mean = sum(
        weight * ret for weight, ret in zip(weights, returns, strict=True)
    ) / 2
    assert math.isclose(sum(contributions), weighted_mean)
