from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts/run_phase5_breadth_opportunity_conversion.py"
)
SPEC = importlib.util.spec_from_file_location("phase5_mechanism", SCRIPT)
assert SPEC and SPEC.loader
phase5 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(phase5)


def test_fixed_outcomes_and_unclipped_capture() -> None:
    frame = pd.DataFrame(
        {
            "mfe": [0.25, 0.10, 0.60],
            "round_trip_return": [0.20, -0.11, -0.30],
        }
    )
    result = phase5.add_fixed_outcomes(frame)
    assert result.opportunity20.tolist() == [True, False, True]
    assert result.converted20.tolist() == [True, False, False]
    assert result.severe_loss.tolist() == [False, True, True]
    assert result.capture_ratio_opportunity20.iloc[0] == pytest.approx(0.8)
    assert np.isnan(result.capture_ratio_opportunity20.iloc[1])
    assert result.capture_ratio_opportunity20.iloc[2] == pytest.approx(-0.5)


def test_within_year_composite_uses_equal_rank_weights() -> None:
    frame = pd.DataFrame(
        {
            "entry_year": [2020, 2020, 2020, 2021, 2021, 2021],
            "breadth_above_ma20": [1, 2, 3, 10, 20, 30],
            "breadth_positive_return20": [1, 2, 3, 10, 20, 30],
            "breadth_above_ma20_change20": [1, 2, 3, 10, 20, 30],
        }
    )
    result = phase5.add_breadth_composite(frame, minimum=6)
    assert result.breadth_composite.tolist() == pytest.approx(
        [1 / 3, 2 / 3, 1.0, 1 / 3, 2 / 3, 1.0]
    )


def test_safe_spearman_fails_closed_on_small_sample() -> None:
    result = phase5.safe_spearman([1, 2, 3], [1, 2, 3], minimum=4)
    assert result == {"n": 3, "rho": None, "p_value": None}


def test_h8_entry_primary_verdict() -> None:
    stable_positive = {"rho": 0.2, "loyo_same_sign_count": 8}
    weak = {"rho": 0.05, "loyo_same_sign_count": 8}
    endpoints = {
        "mfe": stable_positive,
        "opportunity20": stable_positive,
        "conversion20_within_opportunity": weak,
        "capture_ratio_opportunity20": weak,
        "giveback_from_peak": weak,
    }
    verdict = phase5.mechanism_verdict(endpoints)
    assert verdict["h8_verdict"] == "SUPPORTED_ENTRY_OPPORTUNITY_PRIMARY_WITH_QUALIFICATION"


def test_phase5_spec_is_frozen() -> None:
    spec, frame, _ = phase5.validate_and_join()
    assert spec["status"] == "FROZEN_BEFORE_MECHANISM_RESULT"
    assert len(frame) == 399
