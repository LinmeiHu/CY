from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "research/market_behavior_os_v2/scripts/run_mkt_support_geo_001.py"
MODULE_SPEC = importlib.util.spec_from_file_location("run_mkt_support_geo_001", SCRIPT)
assert MODULE_SPEC and MODULE_SPEC.loader
geo = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(geo)


def test_frozen_geometry_spec_and_controls() -> None:
    spec = geo._load_spec()
    assert geo.sha256_file(geo.SPEC_PATH) == geo.EXPECTED_SPEC_SHA256
    assert spec["outcome_access"] is False
    assert len(spec["roles"]) == 6
    assert spec["coordinate_policy"]["pit_historical"] == "UNAVAILABLE_NO_FABRICATION"


def test_generic_minute_controls_are_exact_on_toy_path() -> None:
    rows = pd.DataFrame(
        {
            "open": np.full(241, 10.0),
            "high": np.full(241, 11.0),
            "low": np.full(241, 9.0),
            "close": np.full(241, 10.0),
            "volume": np.ones(241),
        }
    )
    rows.loc[1:, "close"] = np.linspace(10.0, 11.0, 240)
    values = geo._minute_controls(rows)
    assert values["minute_open_to_close_return"] == 11.0 / 10.0 - 1.0
    assert values["minute_intraday_range"] == (11.0 - 9.0) / 10.0
    assert values["minute_volume_herfindahl"] == 1.0 / 240.0
    assert values["minute_opening30_volume_share"] == 0.125
    assert values["minute_closing30_volume_share"] == 0.125


def test_adjusted_rank_r2_detects_exact_reconstruction() -> None:
    frame = pd.DataFrame({"target": np.arange(20.0), "control": np.arange(20.0)})
    assert geo._adjusted_rank_r2(frame, "target", ["control"]) == 1.0


def test_relative_rank_uses_average_ties() -> None:
    ranked = geo._rank_pct(pd.Series([1.0, 1.0, 3.0, 4.0]))
    assert ranked.tolist() == [0.25, 0.25, 0.625, 0.875]


def test_completed_artifact_boundaries_when_present() -> None:
    if not geo.RESULT_PATH.exists():
        return
    result = json.loads(geo.RESULT_PATH.read_text(encoding="utf-8"))
    assert result["support_defense_claim"] == "NONE"
    assert result["temporal_claim"] == "NONE"
    assert result["usefulness_claim"] == "NONE"
    assert result["pit_historical_coordinate"] == "UNAVAILABLE_NOT_FABRICATED"
    assert result["future_fields_read"] == []
    assert result["strategy_or_outcome_fields_read"] == []
    assert result["post_2023_data_read"] is False
    assert result["cy011_read"] is False
    assert result["partition_content_hashes_verified"] is True
    assert geo.sha256_file(geo.SESSION_PATH) == result["hashes"]["session_panel_sha256"]
    assert geo.sha256_file(geo.TRAJECTORY_PATH) == result["hashes"]["trajectory_panel_sha256"]
