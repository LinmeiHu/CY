# ruff: noqa: E501
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd

MODULE_PATH = Path(__file__).with_name("run_setup_accumulation_funnel.py")
SPEC = importlib.util.spec_from_file_location("setup_accumulation_funnel", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_wilson_interval_contains_observed_rate() -> None:
    low, high = MODULE.wilson(37, 100)
    assert low < 0.37 < high


def test_deterministic_controls_are_exact_date_board_and_unique() -> None:
    waves = pd.DataFrame(
        [
            {"event_id": "w1", "symbol": "000001.SZ", "feature_date": pd.Timestamp("2020-01-02"), "feature_position": 0, "split": "discovery"},
            {"event_id": "w2", "symbol": "300001.SZ", "feature_date": pd.Timestamp("2020-01-02"), "feature_position": 0, "split": "discovery"},
        ]
    )
    labels = pd.DataFrame(
        [
            {"symbol": "000002.SZ", "feature_date": pd.Timestamp("2020-01-02"), "feature_position": 0, "split": "discovery", "any_upside": False},
            {"symbol": "300002.SZ", "feature_date": pd.Timestamp("2020-01-02"), "feature_position": 0, "split": "discovery", "any_upside": False},
        ]
    )
    original = MODULE.EXPECTED_WAVES
    MODULE.EXPECTED_WAVES = 2
    try:
        result = MODULE.deterministic_matched_controls(waves, labels)
    finally:
        MODULE.EXPECTED_WAVES = original
    assert result["control_event_id"].is_unique
    assert set(result["feature_date"]) == {pd.Timestamp("2020-01-02")}
    assert set(result["board"]) == {"MAIN", "CHINEXT"}


def test_nested_root_cause_preserves_authoritative_first_blocker() -> None:
    row = pd.Series(
        {
            "first_failed_gate": "hard_valid",
            "ensemble_ambiguity": True,
            "base_exists": False,
            "strict_temporal_valid": False,
            "setup_created": False,
        }
    )
    assert MODULE.nested_root_cause(row) == "ENSEMBLE_PEAK_AMBIGUOUS"
