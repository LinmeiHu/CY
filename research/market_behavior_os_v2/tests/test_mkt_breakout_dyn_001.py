from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
RUNNER = PROGRAM / "scripts/run_mkt_breakout_dyn_001.py"


def _module():
    spec = importlib.util.spec_from_file_location("run_mkt_breakout_dyn_001_test", RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_frozen_spec_and_map_identity() -> None:
    module = _module()
    spec, parent = module._load_spec()
    assert _sha256(module.SPEC_PATH) == module.EXPECTED_SPEC_SHA256
    temporal = spec["inputs"]["temporal_dynamics_map"]
    assert _sha256(ROOT / temporal["path"]) == temporal["sha256"]
    assert parent["representation_summary"]["minimal_roles"] == list(spec["roles"])


def test_temporal_operators_preserve_actual_market_session_gaps() -> None:
    module = _module()
    two = module._operators(np.array([1.0, 5.0]), np.array([2.0, 10.0]))
    assert two["endpoint_rate"] == 2.0
    assert np.isnan(two["ols_slope"])
    assert np.isnan(two["theil_sen_slope"])

    three = module._operators(
        np.array([1.0, 3.0, 5.0]), np.array([2.0, 6.0, 10.0])
    )
    assert three == {
        "endpoint_rate": 2.0,
        "ols_slope": 2.0,
        "theil_sen_slope": 2.0,
    }


def test_trajectory_builder_does_not_fill_non_event_days() -> None:
    module = _module()
    source = pd.DataFrame(
        {
            "sequence_id": ["S", "S"],
            "target_year": [2020, 2020],
            "temporal_block": ["A", "A"],
            "market_view": ["ALL_A", "ALL_A"],
            "symbol": ["000001.SZ", "000001.SZ"],
            "trade_date": pd.to_datetime(["2020-01-02", "2020-01-08"]),
            "market_sequence_rank": [1, 5],
            "definition": ["L20_CONTINUOUS", "L20_CONTINUOUS"],
            "domain_main": [True, True],
            "target": [1.0, 5.0],
            "control": [3.0, 11.0],
        }
    )
    spec = {
        "roles": {
            "target": {
                "domain_flag": "domain_main",
                "controls": ["control"],
            }
        }
    }
    trajectory = module._build_trajectories(spec, source)
    assert len(trajectory) == 1
    assert trajectory.loc[0, "event_days"] == 2
    assert trajectory.loc[0, "rank_span"] == 4
    assert trajectory.loc[0, "endpoint_rate"] == 1.0
    assert trajectory.loc[0, "control__control__endpoint_rate"] == 2.0


def test_bootstrap_interval_is_deterministic() -> None:
    module = _module()
    values = np.array([-2.0, -1.0, 0.0, 1.0, 2.0])
    first = module._bootstrap_interval(values, "role", "A", 100)
    second = module._bootstrap_interval(values, "role", "A", 100)
    assert first == second
