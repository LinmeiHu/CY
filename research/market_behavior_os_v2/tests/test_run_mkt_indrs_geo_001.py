from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "research/market_behavior_os_v2/scripts/run_mkt_indrs_geo_001.py"
MODULE_SPEC = importlib.util.spec_from_file_location("run_mkt_indrs_geo_001", SCRIPT)
assert MODULE_SPEC and MODULE_SPEC.loader
geometry = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(geometry)


def test_frozen_spec_and_bound_input_identities() -> None:
    spec = geometry._load_spec()
    assert geometry.sha256_file(geometry.SPEC_PATH) == geometry.EXPECTED_SPEC_SHA256
    paths = geometry._input_paths(spec)
    for source, entry in spec["inputs"].items():
        assert geometry.sha256_file(paths[source]["panel"]) == entry["panel_sha256"]
        assert geometry.sha256_file(paths[source]["result"]) == entry["result_sha256"]


def test_role_specific_control_sets_are_small_and_frozen() -> None:
    spec = geometry._load_spec()
    assert set(spec["targets"]) == set(spec["role_control_sets"])
    assert all(1 <= len(controls) <= 3 for controls in spec["role_control_sets"].values())
    assert all(control in spec["controls"] for controls in spec["role_control_sets"].values() for control in controls)
    serialized = json.dumps({"targets": spec["targets"], "controls": spec["controls"]}).lower()
    assert "industry_diffusion_ma" not in serialized
    assert "future" not in serialized
    assert "pnl" not in serialized


def test_adjusted_rank_r2_exact_reconstruction() -> None:
    frame = pd.DataFrame({
        "target": np.arange(1.0, 21.0),
        "control": np.arange(1.0, 21.0),
        "noise": [0.0, 1.0] * 10,
    })
    assert np.isclose(geometry.adjusted_rank_r2(frame, "target", ["control"]), 1.0)
    assert geometry.adjusted_rank_r2(frame, "target", ["control", "noise"]) <= 1.0


def test_relative_geometry_pools_governed_views_by_denominator() -> None:
    spec = geometry._load_spec()
    panel, _ = geometry.load_bound_inputs(spec)
    relative = geometry._analysis_groups(panel, spec, "relative_rank")
    relative_to_all = geometry._analysis_groups(panel, spec, "relative_to_all")
    assert [name for name, _ in relative] == ["ALL_STATUS", "NON_ST"]
    assert [name for name, _ in relative_to_all] == ["ALL_STATUS", "NON_ST"]
    assert all(group["market_view"].nunique() == 4 for _, group in relative)
    assert all(group["market_view"].nunique() == 3 for _, group in relative_to_all)


def test_bound_common_population_and_availability() -> None:
    panel, audit = geometry.load_bound_inputs(geometry._load_spec())
    assert len(panel) == 10696
    assert panel.duplicated(geometry.KEYS).sum() == 0
    assert panel.groupby(["market_view", "denominator"]).size().eq(1337).all()
    assert set(audit) == {
        "industry", "breadth", "correlation_liquidity", "leadership", "volatility", "risk_appetite",
    }
    assert panel["geometry_decision_at"].str.endswith("T15:00:00+08:00").all()


def test_completed_artifact_boundaries_when_present() -> None:
    if not geometry.RESULT_PATH.exists() or not geometry.PANEL_PATH.exists():
        return
    result = json.loads(geometry.RESULT_PATH.read_text(encoding="utf-8"))
    assert result["future_values_read"] == []
    assert result["market_return_fields_read"] == []
    assert result["strategy_or_outcome_fields_read"] == []
    assert result["failed_industry_roles_read"] == []
    assert result["failed_ma_industry_fields_read"] == []
    assert result["cy011_read"] is False
    assert result["usefulness_claim"] == "NONE"
    assert geometry.sha256_file(geometry.PANEL_PATH) == result["hashes"]["panel_sha256"]
