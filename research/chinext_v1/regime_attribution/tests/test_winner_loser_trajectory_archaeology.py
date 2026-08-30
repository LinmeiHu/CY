from __future__ import annotations

import math
import sys
from pathlib import Path

import pandas as pd
import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run_winner_loser_trajectory_archaeology as archaeology


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0.50, "extreme_winner"),
        (0.20, "strong_winner"),
        (0.01, "ordinary_winner"),
        (0.0, "ordinary_loser"),
        (-0.099, "ordinary_loser"),
        (-0.10, "severe_loser"),
    ],
)
def test_fixed_outcome_class_boundaries(value: float, expected: str) -> None:
    assert archaeology.classify_outcome(value) == expected


def test_feature_window_uses_exact_causal_twenty_step_window() -> None:
    rows = pd.DataFrame(
        {
            "cal_idx": range(21),
            "critical_valid": [True] * 21,
            "coordinate_step_valid": [False] + [True] * 20,
            "step_log_return": [float("nan")] + [0.01] * 20,
            "adjusted_close": [100.0 + value for value in range(21)],
            "adjusted_high": [101.0 + value for value in range(21)],
            "adjusted_low": [99.0 + value for value in range(21)],
            "amount": [1_000_000.0] * 21,
        }
    )
    metrics = archaeology.feature_window(rows, {0: 100.0, 20: 100.0}, 20)
    assert metrics["relative_strength20"] == pytest.approx(0.20)
    assert metrics["realized_vol20"] == pytest.approx(0.0)
    assert metrics["downside_amount_share20"] == pytest.approx(0.0)
    assert metrics["amount_ratio5_to_prior15"] == pytest.approx(1.0)
    assert metrics["higher_low10"] == pytest.approx(math.log(110.0 / 100.0))


def test_bh_adjustment_is_monotone_in_ranked_p_values() -> None:
    adjusted = archaeology.bh_adjust({"a": 0.01, "b": 0.03, "c": 0.20, "missing": None})
    assert adjusted["a"] <= adjusted["b"] <= adjusted["c"]
    assert adjusted["missing"] is None
