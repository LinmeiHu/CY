from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

RUNNER = Path(__file__).resolve().parents[1] / "scripts/run_mkt_breakout_001.py"
MODULE_SPEC = importlib.util.spec_from_file_location("run_mkt_breakout_001_tested", RUNNER)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
module = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(module)


def _path() -> tuple[np.ndarray, ...]:
    open_price = np.full(241, 10.0)
    high = np.full(241, 9.9)
    low = np.full(241, 9.7)
    close = np.full(241, 10.2)
    volume = np.ones(241)
    high[1] = 10.5
    close[1] = 10.2
    close[2] = 9.8
    close[3] = 10.1
    amount = volume * close
    return open_price, high, low, close, volume, amount


def test_descriptor_separates_cross_bar_from_strictly_after_path() -> None:
    descriptor = module.path_descriptor(*_path(), 1.0, 10.0, include_auction=False)
    assert descriptor["first_cross_index"] == 0
    assert descriptor["remaining_bars"] == 239
    assert np.isclose(descriptor["follow_through_excursion"], -0.01)
    assert np.isclose(descriptor["rejection_depth"], -0.03)
    assert descriptor["crossing_bar_activity_ratio"] is None


def test_descriptor_counts_loss_reacquisition_and_above_episodes() -> None:
    descriptor = module.path_descriptor(*_path(), 1.0, 10.0, include_auction=False)
    assert descriptor["loss_episode_count"] == 1.0
    assert descriptor["reacquisition_bars"] == 1.0
    assert descriptor["above_level_close_episode_count"] == 2.0
    assert descriptor["domain_reacquisition"] is True


def test_rank_adjusted_r2_identifies_exact_control_reconstruction() -> None:
    frame = pd.DataFrame(
        {
            "target": [1.0, 2.0, 3.0, 4.0, 5.0],
            "control": [10.0, 20.0, 30.0, 40.0, 50.0],
        }
    )
    assert module._rank_adjusted_r2(frame, "target", ["control"]) == 1.0
