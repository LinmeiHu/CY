from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "research/market_behavior_os_v2/scripts/run_mkt_min_path_001.py"
MODULE_SPEC = importlib.util.spec_from_file_location("run_mkt_min_path_001", SCRIPT)
assert MODULE_SPEC and MODULE_SPEC.loader
pathmod = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(pathmod)


def test_frozen_spec_and_old_shape_prohibition() -> None:
    assert pathmod.sha256_file(pathmod.SPEC_PATH) == pathmod.EXPECTED_SPEC_SHA256
    spec = json.loads(pathmod.SPEC_PATH.read_text(encoding="utf-8"))
    merged = pathmod._load_spec()
    assert sum(len(values) for values in merged["descriptors"].values()) == 12
    assert list(merged["operators"]) == list(pathmod.OPERATORS)
    assert merged["inputs"]["raw_minute_rescan"] == "PROHIBITED"
    assert spec["only_semantic_correction"]["trajectory_available_at"].startswith("Day -1 15:30")


def test_nonslope_operators_have_fixed_order_reversal_and_curvature_semantics() -> None:
    values = np.array([
        [1, 2, 3, 4, 5],
        [5, 4, 3, 2, 1],
        [1, 2, 3, 2, 1],
        [1, 1, 1, 1, 1],
    ], dtype=float)
    out = pathmod.nonslope_operators(values)
    assert out["ordinal_progression"].tolist() == [1.0, -1.0, 0.0, 0.0]
    assert out["signed_reversal"].tolist() == [0.0, 0.0, -1.0, 0.0]
    assert out["curvature"].tolist() == [0.0, 0.0, -2.0, 0.0]
    assert out["ordinal_progression_neighbor_rank_time"][0] == 1.0
    assert out["ordinal_progression_neighbor_rank_time"][1] == -1.0


def test_bound_adapter_reads_only_five_day_and_daily_aggregation_fields() -> None:
    daily, trajectory = pathmod.load_bound_inputs(pathmod._load_spec())
    assert len(daily) == 11656
    assert len(trajectory) == 11624
    forbidden = ("ols_slope", "endpoint", "signed_monotonic", "slope_acceleration", "reversal_shape")
    assert not any(token in column for column in [*daily.columns, *trajectory.columns] for token in forbidden)
    assert trajectory.trade_date.max() <= pd.Timestamp("2023-12-31")


def test_completed_artifact_preserves_boundaries_when_present() -> None:
    if not pathmod.RESULT_PATH.exists() or not pathmod.PANEL_PATH.exists():
        return
    result = json.loads(pathmod.RESULT_PATH.read_text(encoding="utf-8"))
    assert result["raw_minute_rows_read"] == 0
    assert result["forbidden_old_shape_fields_read"] == []
    assert result["strategy_or_outcome_fields_read"] == []
    assert result["mechanism_claim"] == "NONE"
    assert pathmod.sha256_file(pathmod.PANEL_PATH) == result["hashes"]["panel_sha256"]
