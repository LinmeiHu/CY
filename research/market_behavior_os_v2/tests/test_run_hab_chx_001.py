from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "research/market_behavior_os_v2/scripts/run_hab_chx_001.py"
MODULE_SPEC = importlib.util.spec_from_file_location("run_hab_chx_001", SCRIPT)
assert MODULE_SPEC and MODULE_SPEC.loader
habitat = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(habitat)


def test_frozen_spec_identity() -> None:
    assert habitat.sha256_file(habitat.SPEC_PATH) == habitat.EXPECTED_SPEC_SHA256


def test_state_cell_semantics() -> None:
    a = pd.Series([-1.0, 1.0, -1.0, 1.0, 0.0])
    b = pd.Series([-1.0, -1.0, 1.0, 1.0, 1.0])
    assert habitat._state_cell(a, b).tolist() == [
        "NEITHER",
        "A_ONLY",
        "B_ONLY",
        "A_AND_B",
        "B_ONLY",
    ]


def test_partial_rank_removes_shared_linear_rank_component() -> None:
    control = np.arange(30, dtype=float)
    left = control + np.tile([-1.0, 0.0, 1.0], 10)
    right = control + np.tile([1.0, 0.0, -1.0], 10)
    raw = habitat._correlation(left, right)
    partial = habitat._correlation(left, right, control)
    assert raw > 0.9
    assert partial < -0.9


def test_nested_model_detects_fixed_interaction() -> None:
    a = np.repeat(np.array([-0.2, -0.1, 0.1, 0.2]), 30)
    b = np.tile(np.repeat(np.array([-0.02, -0.01, 0.01, 0.02]), 5), 6)
    outcome = 1.0 + (a / 0.1) * (b / 0.01)
    frame = pd.DataFrame(
        {
            "outcome": outcome,
            "A_trend_direction": a,
            "B_breadth_discovery": b,
        }
    )
    fitted = habitat._fit_ols(frame, "outcome", "A+B")
    assert np.isclose(fitted["coefficients"]["A_x_B"], 1.0)
    assert np.isclose(fitted["r_squared"], 1.0)


def test_primary_population_reconciles_before_full_analysis() -> None:
    spec = habitat.json.loads(habitat.SPEC_PATH.read_text(encoding="utf-8"))
    state = habitat.load_market_state(spec)
    events, daily = habitat.load_strategy_process(spec, state)
    cycles = habitat.load_completed_cycles(spec, state, events)
    assert len(state) == len(daily) == 1337
    assert len(events) == 819
    assert int(events.admissible_candidate.sum()) == 638
    assert int(events.selected_admission.sum()) == 280
    assert len(cycles) == 280
    assert cycles.entry_execution_date.gt(cycles.entry_signal_date).all()
    panel = habitat.build_panel(daily, events, cycles)
    assert len(panel) == 1337 + 819 + 280
    assert panel.columns.is_unique
