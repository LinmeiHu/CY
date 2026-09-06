from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts/run_phase6_winner_loss_conversion_mechanisms.py"
)
SPEC = importlib.util.spec_from_file_location("phase6_mechanisms", SCRIPT)
assert SPEC and SPEC.loader
phase6 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(phase6)


def test_deterministic_top_flag_breaks_pnl_tie_by_trade_id() -> None:
    frame = pd.DataFrame(
        {
            "trade_id": ["b", "a", "c"],
            "realized_pnl": [10.0, 10.0, 5.0],
            "exit_year": [2020, 2020, 2020],
        }
    )
    assert phase6.deterministic_top_flag(frame, 1).tolist() == [False, True, False]
    assert phase6.deterministic_top_flag(frame, 1, "exit_year").tolist() == [False, True, False]


def test_fixed_archetype_boundaries() -> None:
    frame = pd.DataFrame(
        {
            "trade_id": ["a", "b", "c"],
            "realized_pnl": [1.0, -1.0, -2.0],
            "round_trip_return": [0.20, 0.0, -0.20],
            "mfe": [0.20, 0.20, 0.09],
            "exit_year": [2020, 2020, 2020],
            "false_breakout": [False, False, True],
            "severe_loss": [False, False, True],
            "extreme_loss": [False, False, True],
        }
    )
    result = phase6.add_fixed_archetypes(frame)
    assert result.winner20.tolist() == [True, False, False]
    assert result.failed_opportunity20.tolist() == [False, True, False]
    assert result.lost_opportunity20.tolist() == [False, True, False]
    assert result.false_breakout.tolist() == [False, False, True]


def test_partial_rank_recovers_residual_monotone_relation() -> None:
    size = 80
    x = np.linspace(0.01, 0.99, size)
    frame = pd.DataFrame(
        {
            "breadth_composite": x,
            "capture_ratio_opportunity20": x + 0.01 * np.sin(np.arange(size)),
            "mfe": np.tile(np.linspace(0.2, 0.8, 10), 8),
            "holding_trading_days": np.tile(np.arange(1, 9), 10),
            "time_to_mfe_fraction": np.tile([0.1, 0.3, 0.6, 0.9], 20),
            "entry_year": np.repeat(np.arange(2018, 2026), 10),
            "canonical_exit_reason": np.tile(["A", "B"], 40),
        }
    )
    result = phase6.partial_rank(frame, "capture_ratio_opportunity20")
    assert result["n"] == size
    assert result["partial_rank_rho"] is not None
    assert result["partial_rank_rho"] > 0.95


def test_partial_rank_fails_closed_below_minimum() -> None:
    frame = pd.DataFrame(
        {
            "breadth_composite": [0.1, 0.2],
            "capture_ratio_opportunity20": [0.1, 0.2],
            "mfe": [0.2, 0.3],
            "holding_trading_days": [1, 2],
            "time_to_mfe_fraction": [0.1, 0.2],
            "entry_year": [2020, 2021],
            "canonical_exit_reason": ["A", "B"],
        }
    )
    result = phase6.partial_rank(frame, "capture_ratio_opportunity20", minimum=3)
    assert result == {"n": 2, "partial_rank_rho": None, "p_value": None}


def test_phase6_spec_and_frozen_inputs_validate() -> None:
    spec, frame, phase5, _ = phase6.validate_inputs()
    assert spec["status"] == "FROZEN_BEFORE_ARCHETYPE_RESULT"
    assert phase5["experiment_id"] == "EXP-P5-001"
    assert len(frame) == 399
    assert int(frame.breadth_composite.notna().sum()) == 383
