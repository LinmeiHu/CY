from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "research/market_behavior_os_v2/scripts/run_mkt_min_vol_state_001.py"
MODULE_SPEC = importlib.util.spec_from_file_location("run_mkt_min_vol_state_001", SCRIPT)
assert MODULE_SPEC and MODULE_SPEC.loader
statemod = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(statemod)


def test_frozen_spec_and_input_hashes() -> None:
    spec = statemod._load_spec()
    assert statemod.sha256_file(statemod.SPEC_PATH) == statemod.EXPECTED_SPEC_SHA256
    paths = statemod._input_paths(spec)
    assert statemod.sha256_file(paths["path_panel"]) == spec["inputs"]["path_panel"]["sha256"]
    assert statemod.sha256_file(paths["geometry_result"]) == spec["inputs"]["geometry_result"]["sha256"]
    assert spec["availability"]["current_state_available_at"].endswith("15:30 Asia/Shanghai")


def test_exact_state_boundaries() -> None:
    assert statemod.path_state(1e-12) == "RISING"
    assert statemod.path_state(-1e-12) == "FALLING"
    assert statemod.path_state(0.0) == "FLAT"
    assert statemod.path_state(float("nan")) == "MISSING"
    assert statemod.level_state(0.20) == "LOW_LEVEL"
    assert statemod.level_state(0.80) == "HIGH_LEVEL"
    assert statemod.level_state(0.50) == "MIDDLE_LEVEL"


def test_state_metrics_and_completed_runs() -> None:
    labels = pd.Series(["RISING", "RISING", "FLAT", "FALLING", "FALLING"])
    assert statemod.cohen_kappa(labels, labels) == 1.0
    assert statemod.macro_jaccard(labels, labels) == 1.0
    runs = statemod.completed_run_lengths(pd.Series(["RISING", "RISING", "FLAT", "FALLING", "RISING"]))
    assert runs["RISING"] == []
    assert runs["FLAT"] == [1]
    assert runs["FALLING"] == [1]
    transition = statemod.transition_distribution(labels)
    assert np.isclose(transition.sum(), 1.0)


def test_bound_join_exact_population_and_allowlist() -> None:
    panel = statemod.load_bound_inputs(statemod._load_spec())
    assert len(panel) == 10696
    assert panel.groupby(["market_view", "denominator"]).size().eq(1337).all()
    forbidden = ("signed_reversal", "curvature", "ols_", "endpoint", "pnl", "mfe", "mae")
    assert not any(token in column.lower() for column in panel.columns for token in forbidden)
    assert panel["state_available_at"].str.endswith("15:30:00+08:00").all()


def test_completed_artifact_boundaries_when_present() -> None:
    if not statemod.RESULT_PATH.exists() or not statemod.PANEL_PATH.exists():
        return
    result = json.loads(statemod.RESULT_PATH.read_text(encoding="utf-8"))
    assert result["raw_minute_rows_read"] == 0
    assert result["future_market_outcomes_read"] == []
    assert result["strategy_or_outcome_fields_read"] == []
    assert result["usefulness_claim"] == "NONE"
    assert statemod.sha256_file(statemod.PANEL_PATH) == result["hashes"]["panel_sha256"]
