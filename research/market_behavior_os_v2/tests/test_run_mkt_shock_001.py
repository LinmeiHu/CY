from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "research/market_behavior_os_v2/scripts/run_mkt_shock_001.py"
MODULE_SPEC = importlib.util.spec_from_file_location("run_mkt_shock_001", SCRIPT)
assert MODULE_SPEC and MODULE_SPEC.loader
shock = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(shock)


def test_frozen_spec_identity() -> None:
    assert shock.sha256_file(shock.SPEC_PATH) == shock.EXPECTED_SPEC_SHA256


def test_state_machine_uses_only_causal_running_episode_state() -> None:
    score = np.array([0.2, 0.91, 0.93, 0.8, 0.92, 0.6, 0.49, 0.96])
    activity = np.array([0.5, 0.9, 0.8, 0.2, 0.8, 0.05, 0.4, 0.9])
    result = shock.build_episode(score, activity, 0.90, 0.50, 0.10)
    assert result.state.tolist() == [
        "NORMAL",
        "ONSET",
        "STRESS",
        "RELIEF",
        "STRESS",
        "RELIEF",
        "NORMAL",
        "ONSET",
    ]
    assert result.onset.tolist() == [False, True, False, False, False, False, False, True]
    assert result.episode_id.dropna().tolist() == [1, 1, 1, 1, 1, 2]
    assert result.episode_age.dropna().tolist() == [1, 2, 3, 4, 5, 1]
    assert result.activity_impairment.tolist() == [False, False, False, False, False, True, False, False]
    assert np.isclose(result.stress_relief.iloc[3], 0.13)
    assert np.isclose(result.stress_relief.iloc[5], 0.33)


def test_missing_state_breaks_episode_without_imputation() -> None:
    result = shock.build_episode(
        np.array([0.91, np.nan, 0.92]),
        np.array([0.9, 0.9, 0.9]),
        0.90,
        0.50,
        0.10,
    )
    assert result.state.tolist() == ["ONSET", "MISSING", "ONSET"]
    assert result.episode_id.dropna().tolist() == [1, 2]


def test_onset_matching_uses_session_distance() -> None:
    primary = pd.Series([False, True, False, False, True, False])
    neighbor = pd.Series([False, False, True, False, False, False])
    assert shock._event_match_ratio(primary, neighbor, tolerance=1) == 0.5
    assert shock._event_match_ratio(primary, neighbor, tolerance=2) == 1.0


def test_empty_neighbor_metric_is_explicitly_missing() -> None:
    summary = shock._finite_summary([float("nan"), float("nan")])
    assert np.isnan(summary["minimum"])
    assert np.isnan(summary["median"])


def test_bound_panel_population_and_forbidden_change_exclusion() -> None:
    spec = shock.json.loads(shock.SPEC_PATH.read_text(encoding="utf-8"))
    panel = shock.load_bound_panels(spec)
    assert len(panel) == 10696
    assert panel.groupby(["market_view", "denominator"]).size().eq(1337).all()
    assert not any(column.startswith("liquidity_activity_change") for column in panel)
