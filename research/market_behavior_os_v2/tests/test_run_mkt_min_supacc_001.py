from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "research/market_behavior_os_v2/scripts/run_mkt_min_supacc_001.py"
MODULE_SPEC = importlib.util.spec_from_file_location("run_mkt_min_supacc_001", SCRIPT)
assert MODULE_SPEC and MODULE_SPEC.loader
mechanism = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(mechanism)


def test_frozen_spec_and_input_identities() -> None:
    spec = mechanism._load_spec()
    assert mechanism.sha256_file(mechanism.SPEC_PATH) == mechanism.EXPECTED_SPEC_SHA256
    paths = mechanism._input_paths(spec)
    for name, path in paths.items():
        assert mechanism.sha256_file(path) == spec["inputs"][name]["sha256"]
    assert list(spec["mechanisms"]) == [
        "vwap_defense_recovery",
        "late_vwap_acceptance",
        "price_volume_demand_balance",
    ]


def test_causal_percentile_exact_current_inclusion() -> None:
    values = pd.Series([3.0, 1.0, 2.0, 4.0, 0.0])
    observed = mechanism.causal_rolling_percentile(values, window=4, min_history=3)
    assert observed.iloc[:2].isna().all()
    assert observed.iloc[2] == 2.0 / 3.0
    assert observed.iloc[3] == 1.0
    assert observed.iloc[4] == 0.25


def test_bound_population_and_derived_availability() -> None:
    spec = mechanism._load_spec()
    panel = mechanism.load_bound_input(spec)
    assert len(panel) == spec["population"]["expected_rows"]
    assert panel.groupby(["market_view", "denominator"]).size().eq(1457).all()
    assert panel["available_at"].str.endswith("T15:30:00").all()
    assert panel["hard_valid"].all()


def test_negative_components_are_aligned_by_one_minus_percentile() -> None:
    spec = mechanism._load_spec()
    panel = mechanism.construct_scores(mechanism.load_bound_input(spec), spec)
    definition = spec["mechanisms"]["vwap_defense_recovery"]
    row = panel.loc[
        panel[
            [mechanism._pit_field(component, "median") for component in (
                definition["positive"] + definition["negative"]
            )]
        ].notna().all(axis=1)
    ].iloc[0]
    aligned = [row[mechanism._pit_field(component, "median")] for component in definition["positive"]]
    aligned.extend(
        1.0 - row[mechanism._pit_field(component, "median")]
        for component in definition["negative"]
    )
    assert row[mechanism._score_field("vwap_defense_recovery", "median", "mean")] == sum(aligned) / 4.0


def test_completed_artifact_boundaries_when_present() -> None:
    if not mechanism.RESULT_PATH.exists() or not mechanism.PANEL_PATH.exists():
        return
    result = json.loads(mechanism.RESULT_PATH.read_text(encoding="utf-8"))
    assert result["usefulness_claim"] == "NONE"
    assert result["cross_day_support_claim"] == "NONE"
    assert result["participant_accumulation_claim"] == "NONE"
    assert result["future_state_fields_read"] == []
    assert result["strategy_or_outcome_fields_read"] == []
    assert result["failed_level_roles_read"] == []
    assert result["failed_path_roles_read"] == []
    assert result["raw_minute_rows_read"] is False
    assert result["post_2023_data_read"] is False
    assert result["cy011_read"] is False
    assert mechanism.sha256_file(mechanism.PANEL_PATH) == result["hashes"]["panel_sha256"]
