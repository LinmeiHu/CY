from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "research/market_behavior_os_v2/scripts/run_mkt_style_part_dyn_001.py"
MODULE_SPEC = importlib.util.spec_from_file_location(
    "run_mkt_style_part_dyn_001", SCRIPT
)
assert MODULE_SPEC and MODULE_SPEC.loader
precursor = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(precursor)


def test_frozen_spec_and_source_identities() -> None:
    spec = precursor._load_spec()
    assert precursor.sha256_file(precursor.SPEC_PATH) == precursor.EXPECTED_SPEC_SHA256
    paths = precursor._input_paths(spec)
    precursor._validate_results(paths)


def test_future_response_is_exact_later_group_shift() -> None:
    spec = precursor._load_spec()
    source, _ = precursor.load_bound_inputs(spec)
    panel = precursor.construct_future_state(source, spec)
    response = precursor._response_fields(spec)["raw"]
    future_response = precursor._response_name(response, 5)
    for _, group in panel.sort_values(precursor.GROUP_KEYS + ["trade_date"]).groupby(
        precursor.GROUP_KEYS, sort=True
    ):
        assert group[precursor._future_date_name(5)].equals(
            group["trade_date"].shift(-5)
        )
        assert group[future_response].equals(group[response].shift(-5))


def test_task_graph_contains_only_frozen_edge_and_neighbors() -> None:
    spec = precursor._load_spec()
    tasks = precursor._tasks(spec)
    names = [task["name"] for task in tasks]
    assert names[:4] == [
        "primary_raw",
        "primary_pit",
        "primary_relative_to_all",
        "primary_relative_rank",
    ]
    assert sum(name.startswith("neighbor_raw__") for name in names) == 2
    assert names[-1] == "phase_zero_primary_raw"
    assert len(tasks) == 7


def test_partial_estimators_are_inherited_from_validated_runner() -> None:
    assert precursor.partial_rank_correlation is precursor.base.partial_rank_correlation
    assert (
        precursor.partial_within_date_correlation
        is precursor.base.partial_within_date_correlation
    )


def test_completed_artifact_boundaries_when_present() -> None:
    if not precursor.RESULT_PATH.exists() or not precursor.PANEL_PATH.exists():
        return
    result = json.loads(precursor.RESULT_PATH.read_text(encoding="utf-8"))
    assert result["usefulness_claim"] == "NONE"
    assert result["size_premium_claim"] == "NONE"
    assert result["strategy_or_habitat_claim"] == "NONE"
    assert result["future_market_payoff_fields_read"] == []
    assert result["future_stock_selection_fields_read"] == []
    assert result["strategy_or_outcome_fields_read"] == []
    assert result["additional_temporal_edges_read"] == []
    assert result["failed_or_redundant_size_predictors_read"] == []
    assert result["post_2023_data_read"] is False
    assert result["cy011_read"] is False
    assert precursor.sha256_file(precursor.PANEL_PATH) == result["hashes"]["panel_sha256"]
