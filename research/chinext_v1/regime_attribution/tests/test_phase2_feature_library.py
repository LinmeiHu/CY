from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts/run_phase2_feature_library.py"
)
SPEC = importlib.util.spec_from_file_location("phase2_feature_library", SCRIPT)
assert SPEC and SPEC.loader
phase2 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(phase2)


def test_causal_one_step_return_rebases_prior_coordinate() -> None:
    actual = phase2.causal_one_step_return(
        previous_close=20.0,
        current_close=10.0,
        share_multiplier=2.0,
        cash_per_share=0.0,
    )
    assert actual == pytest.approx(0.0)


def test_causal_one_step_return_rejects_invalid_coordinate() -> None:
    with pytest.raises(ValueError, match="invalid corporate-action coordinate"):
        phase2.causal_one_step_return(1.0, 1.0, 0.0, 0.0)


def test_limit_tolerance_matches_registered_validator() -> None:
    assert phase2.limit_close_hit(9.9992, 10.0) is True
    assert phase2.limit_close_hit(9.9989, 10.0) is False
    assert phase2.limit_close_hit(10.0, None) is None


def test_cross_sectional_coverage_fails_closed() -> None:
    assert phase2.coverage_value(0.5, 99, 99) is None
    assert phase2.coverage_value(0.5, 94, 100) is None
    assert phase2.coverage_value(0.5, 95, 100) == pytest.approx(0.5)


def test_phase2_spec_is_frozen_and_outcome_blind() -> None:
    spec, _ = phase2.validate_inputs()
    assert spec["status"] == "FROZEN_BEFORE_FEATURE_RESULT_AND_BEFORE_OUTCOME_JOIN"
    assert spec["outcome_analysis_in_this_experiment"] is False
