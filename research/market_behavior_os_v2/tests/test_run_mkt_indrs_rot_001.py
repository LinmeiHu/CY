from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "research/market_behavior_os_v2/scripts/run_mkt_indrs_rot_001.py"
MODULE_SPEC = importlib.util.spec_from_file_location("run_mkt_indrs_rot_001", SCRIPT)
assert MODULE_SPEC and MODULE_SPEC.loader
rotation = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(rotation)


def test_frozen_spec_and_input_identities() -> None:
    spec = rotation._load_spec()
    assert rotation.sha256_file(rotation.SPEC_PATH) == rotation.EXPECTED_SPEC_SHA256
    paths = rotation._input_paths(spec)
    for name, path in paths.items():
        assert rotation.sha256_file(path) == spec["inputs"][name]["sha256"]
    assert list(spec["replications"]) == [
        "delayed_spearman_persistence",
        "kendall_next_block_persistence",
        "displacement_next_block_persistence",
    ]
    assert spec["temporal_blocks"]["evidence_label"] == (
        "CONSUMED_EXPLORATORY_FALSIFICATION_NOT_CONFIRMATION"
    )


def test_causal_percentile_includes_current_and_honors_row_window() -> None:
    values = pd.Series([3.0, 1.0, 2.0, 4.0, 0.0])
    observed = rotation.causal_rolling_percentile(values, window=4, min_history=3)
    assert observed.iloc[:2].isna().all()
    assert observed.iloc[2] == 2.0 / 3.0
    assert observed.iloc[3] == 1.0
    # Position zero has expired; [1,2,4,0] ranks current zero at 0.25.
    assert observed.iloc[4] == 0.25


def test_bound_input_and_alternate_coordinate_semantics() -> None:
    spec = rotation._load_spec()
    panel = rotation.load_bound_input(spec)
    assert len(panel) == spec["population"]["expected_rows"]
    group = panel.loc[
        (panel["market_view"] == "ALL_A") & (panel["denominator"] == "ALL_STATUS")
    ].sort_values("trade_date")
    raw = rotation.DEFINITION_FIELDS["kendall"]
    pit = rotation._field(raw, "pit")
    first_valid = group[pit].first_valid_index()
    assert first_valid is not None
    position = group.index.get_loc(first_valid)
    window = group[raw].iloc[max(0, position - 755): position + 1].dropna()
    value = group.loc[first_valid, raw]
    expected = (int((window < value).sum()) + int((window <= value).sum()) + 1.0) / (
        2.0 * len(window)
    )
    assert len(window) >= 504
    assert group.loc[first_valid, pit] == expected
    assert group[rotation._field(raw, "relative_to_all")].dropna().eq(0.0).all()


def test_future_states_use_exact_frozen_shifts() -> None:
    spec = rotation._load_spec()
    panel = rotation.construct_future_states(rotation.load_bound_input(spec), spec)
    group = panel.loc[
        (panel["market_view"] == "ALL_A") & (panel["denominator"] == "ALL_STATUS")
    ].sort_values("trade_date").reset_index(drop=True)
    delayed = "delayed_spearman_persistence"
    kendall = "kendall_next_block_persistence"
    assert group.loc[0, rotation._future_date_name(delayed)] == group.loc[10, "trade_date"]
    assert group.loc[0, rotation._response_name(delayed, "raw")] == group.loc[
        10, rotation.DEFINITION_FIELDS["spearman"]
    ]
    assert group.loc[0, rotation._future_date_name(kendall)] == group.loc[5, "trade_date"]
    assert group.loc[0, rotation._response_name(kendall, "raw")] == group.loc[
        5, rotation.DEFINITION_FIELDS["kendall"]
    ]
    assert group[rotation._future_date_name(delayed)].tail(10).isna().all()
    assert group[rotation._future_date_name(kendall)].tail(5).isna().all()


def test_temporal_blocks_require_predictor_and_response_inside() -> None:
    spec = rotation._load_spec()
    panel = rotation.construct_future_states(rotation.load_bound_input(spec), spec)
    for replication in spec["replications"]:
        block_a = rotation._block_frame(panel, spec, replication, "block_a_consumed")
        block_b = rotation._block_frame(panel, spec, replication, "block_b_consumed")
        assert block_a["trade_date"].dt.year.min() == 2019
        assert block_a[rotation._future_date_name(replication)].dt.year.max() == 2021
        assert block_b["trade_date"].dt.year.min() == 2022
        assert block_b[rotation._future_date_name(replication)].dt.year.max() == 2023


def test_completed_artifact_boundaries_when_present() -> None:
    if not rotation.RESULT_PATH.exists() or not rotation.PANEL_PATH.exists():
        return
    result = json.loads(rotation.RESULT_PATH.read_text(encoding="utf-8"))
    assert result["evidence_label"] == "CONSUMED_EXPLORATORY_FALSIFICATION_NOT_CONFIRMATION"
    assert result["confirmation_status"] == "INDEPENDENT_FUTURE_TIME_REQUIRED"
    assert result["market_return_fields_read"] == []
    assert result["stock_selection_fields_read"] == []
    assert result["strategy_or_outcome_fields_read"] == []
    assert result["failed_industry_roles_read"] == []
    assert result["failed_ma_industry_fields_read"] == []
    assert result["post_2023_data_read"] is False
    assert result["cy011_read"] is False
    assert result["usefulness_claim"] == "NONE"
    assert rotation.sha256_file(rotation.PANEL_PATH) == result["hashes"]["panel_sha256"]
