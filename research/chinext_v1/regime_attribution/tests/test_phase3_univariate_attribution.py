from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts/run_phase3_univariate_attribution.py"
)
SPEC = importlib.util.spec_from_file_location("phase3_univariate", SCRIPT)
assert SPEC and SPEC.loader
phase3 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(phase3)


def test_spearman_fails_closed_below_minimum() -> None:
    result = phase3.spearman_estimate([1, 2, 3], [3, 2, 1], minimum=4)
    assert result == {
        "n": 3,
        "rho": None,
        "p_value": None,
        "status": "INSUFFICIENT_SAMPLE",
    }


def test_spearman_reports_direction() -> None:
    result = phase3.spearman_estimate(range(10), range(10), minimum=5)
    assert result["rho"] == pytest.approx(1.0)
    assert result["status"] == "ESTIMATED"


def test_cliffs_delta_binary_positive_minus_negative() -> None:
    delta = phase3.cliffs_delta_for_binary([3, 4, 1, 2], [True, True, False, False])
    assert delta == pytest.approx(1.0)


def test_benjamini_hochberg_is_monotone_in_rank() -> None:
    adjusted = phase3.benjamini_hochberg([0.01, 0.04, 0.03, None])
    assert adjusted[0] == pytest.approx(0.03)
    assert adjusted[1] == pytest.approx(0.04)
    assert adjusted[2] == pytest.approx(0.04)
    assert adjusted[3] is None


def test_sign_is_fail_closed_for_missing() -> None:
    assert phase3.sign(None) == 0
    assert phase3.sign(np.nan) == 0
    assert phase3.sign(0.5) == 1
    assert phase3.sign(-0.5) == -1


def test_phase3_spec_binding_is_frozen() -> None:
    spec = phase3.validate_inputs()
    assert spec["experiment_id"] == "EXP-P3-002"
    assert spec["status"] == "FROZEN_BEFORE_FEATURE_OUTCOME_JOIN"
