from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "research/market_behavior_os_v2/scripts/run_mkt_dstress_001.py"
MODULE_SPEC = importlib.util.spec_from_file_location("run_mkt_dstress_001", SCRIPT)
assert MODULE_SPEC and MODULE_SPEC.loader
dstress = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(dstress)


def test_frozen_spec_identity_and_failed_episode_exclusion() -> None:
    assert dstress.sha256_file(dstress.SPEC_PATH) == dstress.EXPECTED_SPEC_SHA256
    spec = json.loads(dstress.SPEC_PATH.read_text(encoding="utf-8"))
    allowed = spec["inputs"]["shock_panel"]["allowed_columns"]
    assert not any("state_primary" in column or "episode_age" in column for column in allowed)
    assert spec["process_configurations"]["primary"] == {
        "entry": 0.8, "reset_below": 0.5, "high_activity": 0.8
    }


def test_directional_episode_is_causal_and_missing_breaks_state() -> None:
    score = np.array([0.2, 0.81, 0.85, 0.7, np.nan, 0.82, 0.45, 0.9])
    activity = np.array([0.5, 0.9, 0.6, 0.85, 0.9, 0.7, 0.9, 0.95])
    out = dstress.build_directional_episode(score, activity, 0.8, 0.5, 0.8)
    assert out.state.tolist() == [
        "NORMAL", "ONSET", "ELEVATED", "RELIEF", "MISSING", "ONSET", "NORMAL", "ONSET"
    ]
    assert out.onset.tolist() == [False, True, False, False, False, True, False, True]
    assert out.episode_age.dropna().tolist() == [1, 2, 3, 1, 1]
    assert out.high_activity.tolist() == [False, True, False, True, False, False, False, True]


def test_bound_adapter_reads_only_frozen_continuous_inputs() -> None:
    panel = dstress.load_bound_panels(dstress._load_spec())
    assert len(panel) == 10696
    assert panel.groupby(["market_view", "denominator"]).size().eq(1337).all()
    assert not any(column.startswith("shock_onset") for column in panel)
    assert not any(column.startswith("episode_age") for column in panel)
    assert panel.trade_date.max() <= pd.Timestamp("2023-12-31")


def test_completed_artifact_preserves_claim_boundaries_when_present() -> None:
    if not dstress.RESULT_PATH.exists() or not dstress.PANEL_PATH.exists():
        return
    result = json.loads(dstress.RESULT_PATH.read_text(encoding="utf-8"))
    panel = pd.read_csv(dstress.PANEL_PATH)
    assert result["strategy_or_outcome_fields_read"] == []
    assert result["failed_shock_episode_fields_read"] == []
    assert result["panic_claim"] == "NONE"
    assert panel.trade_date.max() <= "2023-12-31"
    assert dstress.sha256_file(dstress.PANEL_PATH) == result["hashes"]["panel_sha256"]
