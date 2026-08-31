from __future__ import annotations

import importlib.util
import inspect
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
RUNNER = PROGRAM / "scripts/run_mkt_formdepth_minx_001.py"


def _module():
    spec = importlib.util.spec_from_file_location(
        "run_mkt_formdepth_minx_001_test", RUNNER
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_frozen_explore_boundary_is_sampled_outcome_blind_and_fixed_window() -> None:
    module = _module()
    spec = module._load_spec()
    assert module.sha256_file(module.SPEC_PATH) == module.EXPECTED_SPEC_SHA256
    assert spec["research_level"] == "EXPLORE"
    assert spec["outcome_access"] is False
    assert spec["activation"]["maximum_hash_sample_each_date_view"] == 40
    assert spec["minute_contract"]["event_offsets"] == [-4, -3, -2, -1, 0]
    assert spec["resource_budget"]["publish_minute_cache"] is False
    assert spec["resource_budget"]["durable_security_minute_descriptors"] is False
    prohibited = "|".join(spec["prohibited_computations"])
    assert "future response" in prohibited
    assert "strategy membership" in prohibited
    assert "post-2023" in prohibited
    assert "CY-011" in prohibited
    assert "adverse_log_excursion" not in inspect.getsource(module)


def test_pre_slope_uses_only_four_pre_event_sessions() -> None:
    module = _module()
    values = np.array([[1.0, 2.0, 3.0, 4.0, 100.0], [4.0, 3.0, 2.0, 1.0, -100.0]])
    observed = module._pre_slope(values)
    np.testing.assert_array_equal(observed, np.array([1.0, -1.0]))


def test_feature_frame_keeps_event_level_and_fixed_trajectory_coordinates() -> None:
    module = _module()
    event_date = pd.Timestamp("2023-06-15")
    sample = pd.DataFrame(
        [
            {
                "event_date": event_date,
                "market_view": "ALL_A",
                "denominator": "ALL_STATUS",
                "symbol": "000001.SZ",
                "selection_hash": "a",
                "selection_rank": 1,
                "anchor_crossing_count": 25,
                "own_depth": 0.05,
                "daily_control_complete": True,
                **{name: 0.1 for name in module.CONTROL_COLUMNS},
            }
        ]
    )
    targets = pd.DataFrame(
        [
            {
                "event_date": event_date,
                "market_view": "ALL_A",
                "symbol": "000001.SZ",
                "session_date": event_date + pd.Timedelta(days=offset),
                "event_offset": offset,
            }
            for offset in (-4, -3, -2, -1, 0)
        ]
    )
    descriptor_rows = []
    for step, offset in enumerate((-4, -3, -2, -1, 0), start=1):
        row = {
            "symbol": "000001.SZ",
            "trade_date": event_date + pd.Timedelta(days=offset),
            **{name: float(step) for name in module.RAW_DESCRIPTOR_COLUMNS},
        }
        row["up_minute_volume_share"] = float(step + 1)
        row["down_minute_volume_share"] = float(step)
        descriptor_rows.append(row)
    features, audit = module._feature_frame(
        sample, targets, pd.DataFrame(descriptor_rows)
    )
    assert len(features) == 1
    assert audit.loc[0, "minute_descriptor_count"] == 5
    assert bool(audit.loc[0, "trajectory_complete"])
    assert features.loc[0, "event_volume_asymmetry"] == 1.0
    for descriptor in module.TRAJECTORY_BASES:
        assert features.loc[0, f"pre_slope4_{descriptor}"] == 1.0
        assert features.loc[0, f"event_jump_{descriptor}"] == 2.5


def test_completed_result_boundaries_when_present() -> None:
    result_path = PROGRAM / "artifacts/MKT-FORMDEPTH-MINX-001_result.json"
    if not result_path.exists():
        return
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["research_level"] == "EXPLORE"
    assert result["evaluation"]["decision"] in {
        "EXPLORATORY_MINUTE_PATTERN_MAPPED",
        "SAMPLED_MINUTE_MECHANISM_NOT_ESTIMABLE",
    }
    assert result["minute_cache_published"] is False
    assert result["durable_security_minute_descriptors"] is False
    assert result["future_values_read"] is False
    assert result["strategy_fields_read"] is False
    assert result["post_2023_read"] is False
    assert result["cy011_read"] is False
