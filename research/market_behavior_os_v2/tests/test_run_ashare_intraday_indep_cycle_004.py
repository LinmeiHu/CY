from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd

SCRIPT = Path(__file__).parents[1] / "scripts/run_ashare_intraday_indep_cycle_004.py"
MODULE_SPEC = importlib.util.spec_from_file_location("cycle_004_tested", SCRIPT)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
CYCLE = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_SPEC.name] = CYCLE
MODULE_SPEC.loader.exec_module(CYCLE)


def test_frozen_spec_has_bounded_family_counts_and_next_open_contract() -> None:
    spec = CYCLE._load_spec()
    assert len(spec["track_a"]["families"]) == 7
    assert len(spec["track_b"]["families"]) == 5
    assert "next market-session open" in spec["pit_contract"]["earliest_entry"]
    assert spec["track_a"]["maximum_executable_promotions"] == 2
    assert spec["track_b"]["maximum_executable_promotions"] == 1


def test_daily_control_residual_is_orthogonal() -> None:
    frame = pd.DataFrame(
        {
            "raw_rank": np.linspace(0.01, 1.0, 100),
            "control_return": np.sin(np.arange(100)),
            "control_range": np.cos(np.arange(100)),
            "control_r20": np.linspace(1.0, 0.01, 100) ** 2,
        }
    )
    residual = CYCLE._residualize(frame)
    design = frame[["control_return", "control_range", "control_r20"]]
    assert residual.notna().all()
    assert np.max(np.abs(design.apply(lambda column: np.dot(column, residual)))) < 1e-10
    assert abs(float(residual.sum())) < 1e-10


def test_blocked_replay_is_not_promoted_as_candidate() -> None:
    spec = CYCLE._load_spec()
    replay = {"family": "quiet_vwap_acceptance", "status": "BLOCKED_DATA_CONTRACT"}
    assert CYCLE._classify_replay(spec, replay) == "REPLAY_BLOCKED"
