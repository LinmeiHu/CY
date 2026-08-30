from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
RUNNER = ROOT / "research/market_behavior_os_v2/scripts/run_mkt_support_dyn_001.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location("run_mkt_support_dyn_001_test", RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_frozen_spec_and_bound_inputs_load() -> None:
    module = _load_runner()
    frozen, parent = module._load_spec()
    assert frozen["experiment_id"] == "MKT-SUPPORT-DYN-001"
    assert parent["experiment_id"] == "MKT-SUPPORT-DYN-DATA-004"
    assert frozen["outcome_access"] is False


def test_coordinate_csv_uses_round_trip_float_parser_on_boundary_session() -> None:
    module = _load_runner()
    frozen, _ = module._load_spec()
    _, coordinate, _ = module._load_parent_frames(frozen)
    row = coordinate.loc[
        coordinate["audit_id"].eq("MARKET|2020|02|SH_A|10|600162.SH|2020-04-16")
    ].iloc[0]
    assert row["coordinate_scale"] == float("0.32403374497482107")
    assert 2.0 * row["coordinate_scale"] > row["support_low20"]
    assert bool(row["primary_level_tested"]) is False


def test_temporal_operators_use_actual_day_gaps() -> None:
    module = _load_runner()
    result = module._temporal_operators(np.array([-5.0, -3.0, -1.0]), np.array([8.0, 4.0, 0.0]))
    assert result == {
        "endpoint_rate": -2.0,
        "ols_slope": -2.0,
        "theil_sen_slope": -2.0,
    }


def test_manual_descriptor_matches_vector_semantics_on_auditable_path() -> None:
    module = _load_runner()
    rows = pd.DataFrame(
        {
            "mapped_open": np.full(241, 10.1),
            "mapped_high": np.full(241, 10.2),
            "mapped_low": np.full(241, 10.05),
            "mapped_close": np.full(241, 10.1),
            "volume": np.ones(241),
        }
    )
    rows.loc[11, "mapped_low"] = 9.9
    rows.loc[11:14, "mapped_close"] = [9.95, 9.97, 9.99, 10.0]
    vector = module._session_features(rows, 10.0, False)
    scalar = module._manual_session_descriptor(rows, 10.0, False)
    for field in [
        "tested",
        "recovery_completion",
        "recovery_speed",
        "recovery_volume_intensity",
    ]:
        assert scalar[field] == vector[field]


def test_transition_risk_difference_and_adjacent_neighbor() -> None:
    module = _load_runner()
    frame = pd.DataFrame(
        {
            "first_state": ["R", "R", "F", "F"],
            "last_state": ["R", "F", "R", "F"],
            "adjacent_R_R": [1, 0, 0, 0],
            "adjacent_R_F": [0, 1, 0, 0],
            "adjacent_F_R": [0, 0, 1, 0],
            "adjacent_F_F": [0, 0, 0, 1],
        }
    )
    assert module._transition_risk_difference(frame) == 0.0
    assert module._adjacent_risk_difference(frame) == 0.0
