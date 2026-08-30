from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
RUNNER = ROOT / "research/market_behavior_os_v2/scripts/run_mkt_support_lvl_data_001.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location("run_mkt_support_lvl_data_001_test", RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_frozen_spec_and_inputs_load() -> None:
    module = _load_runner()
    frozen = module._load_spec()
    assert frozen["experiment_id"] == "MKT-SUPPORT-LVL-DATA-001"
    assert frozen["outcome_access"] is False


def test_level_identity_is_exact_binary64() -> None:
    module = _load_runner()
    level = 10.0
    neighbor = np.nextafter(level, np.inf)
    assert module._level_bits(level) != module._level_bits(neighbor)


def test_a_a_b_is_not_constant_and_a_a_is_constant() -> None:
    module = _load_runner()
    view = {
        "name": "L20_CONT",
        "level_horizon": 20,
        "path": "cont",
        "gate_family": "primary",
    }
    rows = pd.DataFrame(
        {
            "h20_cont_tested": [True, True, True],
            "h20_cont_recovery_completion": [True, True, True],
            "h20_cont_recovery_speed": [1.0, 2.0, 3.0],
            "h20_cont_recovery_volume_intensity": [1.1, 1.2, 1.3],
            "support_low20": [10.0, 10.0, 9.9],
        }
    )
    mixed = module._view_count_record(rows, view)
    assert mixed["constant_test_level"] is False
    assert mixed["unique_tested_level_count"] == 2
    constant = module._view_count_record(rows.iloc[:2], view)
    assert constant["constant_test_level"] is True
    assert constant["constant_level_twice_recovered"] is True
