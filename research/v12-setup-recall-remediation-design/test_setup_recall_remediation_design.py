# ruff: noqa: E501
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd

MODULE_PATH = Path(__file__).with_name("run_setup_recall_remediation_design.py")
SPEC = importlib.util.spec_from_file_location("setup_recall_remediation_design", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_temporal_state_precedence_never_fabricates_valid_base() -> None:
    frame = pd.DataFrame(
        [
            {"peak_track_id": "peak-1", "peak_track_state": "TRACKED", "peak_track_ambiguous": False, "peak_track_split": False, "peak_track_merge": False, "peak_track_lost": False},
            {"peak_track_id": None, "peak_track_state": "ENSEMBLE_PEAK_AMBIGUOUS", "peak_track_ambiguous": True, "peak_track_split": False, "peak_track_merge": False, "peak_track_lost": False},
            {"peak_track_id": None, "peak_track_state": "ENSEMBLE_PEAK_AMBIGUOUS", "peak_track_ambiguous": True, "peak_track_split": True, "peak_track_merge": True, "peak_track_lost": True},
            {"peak_track_id": None, "peak_track_state": "PEAK_MISSING", "peak_track_ambiguous": True, "peak_track_split": False, "peak_track_merge": False, "peak_track_lost": False},
        ]
    )
    assert MODULE.classify_temporal_state(frame).tolist() == [
        "VALID_CANONICAL_BASE",
        "ENSEMBLE_AMBIGUOUS",
        "SPLIT",
        "ENSEMBLE_AMBIGUOUS",
    ]


def test_architecture_flags_keep_candidate_and_anchor_eligibility_separate() -> None:
    frame = pd.DataFrame(
        {
            "candidate_first_eligible": [True, True, False],
            "production_setup_created": [False, False, False],
            "base_free_component_count": [1, 0, 2],
            "temporal_state": ["ENSEMBLE_AMBIGUOUS", "VALID_CANONICAL_BASE", "VALID_CANONICAL_BASE"],
            "ambiguity_rate_20": [0.75, 0.0, 0.0],
            "price_candidate_eligible": [True, True, False],
            "price_drawdown_20": [-0.10, 0.0, -0.20],
            "price_return_1": [0.01, 0.01, -0.01],
        }
    )
    flags = MODULE.architecture_flags(frame)
    assert flags["B_CANDIDATE_FIRST"].tolist() == [True, True, False]
    assert flags["C_ENSEMBLE_AMBIGUOUS"].tolist() == [True, False, False]
    assert flags["D_ANY_1_PLUS_VALID_BASE"].tolist() == [False, False, False]


def test_root_anchor_boundary_is_later_than_candidate_creation_but_before_breakout() -> None:
    audit = MODULE.root_anchor_boundary_audit().set_index("lifecycle_stage")
    assert audit.loc["candidate_generation", "unique_immutable_root_economically_required"] == "NO"
    assert audit.loc["candidate_promotion_to_anchor_dependent_accumulation", "unique_immutable_root_economically_required"] == "YES"
    assert audit.loc["breakout_lifecycle", "unique_immutable_root_economically_required"] == "YES"


def test_availability_treats_registered_naive_timestamp_as_exchange_local() -> None:
    values = pd.Series([pd.Timestamp("2020-01-02 15:00:00")])
    dates = pd.Series([pd.Timestamp("2020-01-02")])
    assert MODULE._available_by_decision(values, dates).tolist() == [True]


def test_researchability_criterion_requires_count_and_enrichment() -> None:
    rows = []
    for architecture in MODULE.ARCHITECTURES:
        for split in ("total", "discovery", "validation", "holdout"):
            rows.append(
                {
                    "architecture": architecture,
                    "split": split,
                    "wave_candidates": 150,
                    "control_candidates": 150,
                    "wave_n": 400,
                    "control_n": 400,
                    "wave_recall": 0.375,
                    "control_acceptance": 0.375,
                    "matched_enrichment": 1.0,
                    "matched_enrichment_cluster_low": 0.9,
                    "distinct_candidate_episodes": 150,
                    "candidate_episodes_per_symbol_year": 1.0,
                    "median_candidate_duration": 5.0,
                }
            )
    summary = MODULE.researchability_summary(pd.DataFrame(rows))
    assert not summary["candidate_funnel_researchable"].any()
