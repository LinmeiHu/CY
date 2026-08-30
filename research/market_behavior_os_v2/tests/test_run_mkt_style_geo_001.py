from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "research/market_behavior_os_v2/scripts/run_mkt_style_geo_001.py"
MODULE_SPEC = importlib.util.spec_from_file_location("run_mkt_style_geo_001", SCRIPT)
assert MODULE_SPEC and MODULE_SPEC.loader
geometry = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(geometry)


def test_frozen_spec_and_input_identities() -> None:
    spec = geometry._load_spec()
    assert geometry.sha256_file(geometry.SPEC_PATH) == geometry.EXPECTED_SPEC_SHA256
    paths = geometry._input_paths(spec)
    for source, entries in paths.items():
        assert geometry.sha256_file(entries["panel"]) == spec["inputs"][source]["panel"]["sha256"]
        assert geometry.sha256_file(entries["result"]) == spec["inputs"][source]["result"]["sha256"]
    geometry._validate_source_results(spec, paths)


def test_style_and_control_coordinate_suffixes() -> None:
    assert geometry._style_field("x", "pit") == "x__pit_3y_pct"
    assert geometry._control_field("x", "pit") == "x_pit_3y_pct"
    assert geometry._style_field("x", "relative_to_all") == "x__relative_to_all"
    assert geometry._control_field("x", "relative_to_all") == "x_relative_to_all"


def test_adjusted_rank_r2_recovers_exact_reconstruction() -> None:
    x1 = np.arange(1.0, 101.0)
    x2 = np.asarray([(position * 37) % 101 for position in range(100)], dtype=float)
    frame = pd.DataFrame({"target": x1 + x2, "x1": x1, "x2": x2})
    observed = geometry.adjusted_rank_r2(frame, "target", ["x1", "x2"])
    assert observed > 0.70


def test_completed_artifact_boundaries_when_present() -> None:
    if not geometry.RESULT_PATH.exists() or not geometry.PANEL_PATH.exists():
        return
    result = json.loads(geometry.RESULT_PATH.read_text(encoding="utf-8"))
    assert result["usefulness_claim"] == "NONE"
    assert result["future_values_read"] == []
    assert result["strategy_or_outcome_fields_read"] == []
    assert result["failed_controls_or_style_roles_read"] == []
    assert result["post_2023_data_read"] is False
    assert result["cy011_read"] is False
    assert geometry.sha256_file(geometry.PANEL_PATH) == result["hashes"]["panel_sha256"]


def test_frozen_design_fails_closed_on_within_group_relative_rank() -> None:
    spec = geometry._load_spec()
    panel, _ = geometry.load_bound_inputs(spec)
    roles = geometry._role_fields(spec)
    controls = geometry._control_fields(spec)
    with pytest.raises(
        geometry.StyleGeometryError,
        match=r"support failed: size_structure:relative_rank:ALL_A:ALL_STATUS:2021",
    ):
        geometry.complete_support_audit(panel, spec, roles, controls)
