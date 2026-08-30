from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "research/market_behavior_os_v2/scripts/run_mkt_min_vol_geo_001.py"
MODULE_SPEC = importlib.util.spec_from_file_location("run_mkt_min_vol_geo_001", SCRIPT)
assert MODULE_SPEC and MODULE_SPEC.loader
geomod = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(geomod)


def test_frozen_spec_and_bound_panel_hashes() -> None:
    spec = geomod._load_spec()
    assert geomod.sha256_file(geomod.SPEC_PATH) == geomod.EXPECTED_SPEC_SHA256
    assert geomod.sha256_file(geomod.PARENT_SPEC_PATH) == geomod.EXPECTED_PARENT_SPEC_SHA256
    paths = geomod._input_paths(spec)
    assert geomod.sha256_file(paths["path_panel"]) == spec["inputs"]["path_panel"]["sha256"]
    assert geomod.sha256_file(paths["volatility_panel"]) == spec["inputs"]["volatility_panel"]["sha256"]
    assert spec["availability"]["geometry_decision_at"].endswith("15:30 Asia/Shanghai")
    assert spec["population"]["pit_cell_and_geometry_years"] == [2021, 2022, 2023]


def test_allowlist_excludes_failed_roles_and_outcomes() -> None:
    spec = geomod._load_spec()
    path_columns, vol_columns = geomod._allowed_columns(spec)
    columns = [*path_columns, *vol_columns]
    forbidden_tokens = ("signed_reversal", "curvature", "ols_", "endpoint", "return_forward", "pnl", "mfe", "mae")
    assert not any(token in column.lower() for column in columns for token in forbidden_tokens)
    assert "minute_realized_volatility__ordinal_progression" in path_columns


def test_bound_join_has_exact_population_and_causal_availability() -> None:
    panel = geomod.load_bound_inputs(geomod._load_spec())
    assert len(panel) == 10696
    assert panel.groupby(["market_view", "denominator"]).size().eq(1337).all()
    assert panel["geometry_decision_at"].str.endswith("15:30:00+08:00").all()
    assert panel.trade_date.max() == pd.Timestamp("2023-12-29")


def test_adjusted_rank_reconstruction_bounds() -> None:
    x = np.arange(20, dtype=float)
    frame = pd.DataFrame({"target": x, "left": x, "right": x[::-1]})
    assert geomod.adjusted_rank_r2(frame, "target", ["left"]) == 1.0
    assert geomod.adjusted_rank_r2(frame, "target", ["left", "right"]) > 0.99


def test_completed_artifact_boundaries_when_present() -> None:
    if not geomod.RESULT_PATH.exists() or not geomod.PANEL_PATH.exists():
        return
    result = json.loads(geomod.RESULT_PATH.read_text(encoding="utf-8"))
    assert result["raw_minute_rows_read"] == 0
    assert result["failed_representation_fields_read"] == []
    assert result["strategy_or_outcome_fields_read"] == []
    assert result["usefulness_claim"] == "NONE"
    assert geomod.sha256_file(geomod.PANEL_PATH) == result["hashes"]["panel_sha256"]
