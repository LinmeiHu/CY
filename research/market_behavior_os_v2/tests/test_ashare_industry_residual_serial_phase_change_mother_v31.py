import importlib.util
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

SCRIPT = Path(__file__).resolve().parents[1] / (
    "scripts/run_ashare_industry_residual_serial_phase_change_mother_v31_stage_a.py"
)
MODULE_SPEC = importlib.util.spec_from_file_location("v31_stage_a", SCRIPT)
assert MODULE_SPEC and MODULE_SPEC.loader
stage_a = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(stage_a)

STAGE_B_SCRIPT = SCRIPT.with_name(
    "run_ashare_industry_residual_serial_phase_change_mother_v31_stage_b.py"
)
STAGE_B_MODULE_SPEC = importlib.util.spec_from_file_location("v31_stage_b", STAGE_B_SCRIPT)
assert STAGE_B_MODULE_SPEC and STAGE_B_MODULE_SPEC.loader
stage_b = importlib.util.module_from_spec(STAGE_B_MODULE_SPEC)
STAGE_B_MODULE_SPEC.loader.exec_module(stage_b)


def representation_row(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "signal_date": pd.Timestamp("2019-01-31"),
        "signal_cal_idx": 260,
        "symbol": "000001.SZ",
        "causal_industry": "TEST",
        "prior_serial_dependence": -0.2,
        "recent_serial_dependence": 0.4,
        "serial_phase_change": 0.6,
        "current_residual_return": 0.01,
        "amount": 200.0,
        "same_date_median_amount": 100.0,
    }
    values.update(overrides)
    return values


def test_row_spearman_is_rank_based_and_rejects_degenerate_rows() -> None:
    left = np.array([[1.0, 2.0, 3.0, 4.0], [1.0, 1.0, 1.0, 1.0]])
    right = np.array([[10.0, 30.0, 20.0, 40.0], [1.0, 2.0, 3.0, 4.0]])
    rho, valid = stage_a.row_spearman(left, right)
    assert valid.tolist() == [True, False]
    assert np.isclose(rho[0], 0.8)
    assert np.isnan(rho[1])


def test_candidate_selection_uses_only_frozen_direction_and_industry_winner() -> None:
    frame = pd.DataFrame(
        [
            representation_row(symbol="000001.SZ", serial_phase_change=0.5),
            representation_row(symbol="000002.SZ", serial_phase_change=0.7),
            representation_row(
                symbol="000003.SZ",
                causal_industry="OTHER",
                prior_serial_dependence=0.1,
                serial_phase_change=0.8,
            ),
            representation_row(
                symbol="000004.SZ",
                causal_industry="OTHER",
                current_residual_return=-0.01,
                serial_phase_change=0.9,
            ),
        ]
    )
    selected, before_cooldown = stage_a.select_candidates(frame)
    assert before_cooldown == 1
    assert selected.symbol.tolist() == ["000002.SZ"]


def test_cooldown_is_strictly_more_than_twenty_market_sessions() -> None:
    frame = pd.DataFrame(
        [
            {
                **representation_row(signal_date=pd.Timestamp("2019-01-31"), signal_cal_idx=100),
                "event_id": "a",
            },
            {
                **representation_row(signal_date=pd.Timestamp("2019-02-28"), signal_cal_idx=120),
                "event_id": "b",
            },
            {
                **representation_row(signal_date=pd.Timestamp("2019-03-29"), signal_cal_idx=121),
                "event_id": "c",
            },
        ]
    )
    retained = stage_a.causal_cooldown(frame)
    assert retained.event_id.tolist() == ["a", "c"]


def execution_candidate() -> SimpleNamespace:
    return SimpleNamespace(
        event_id="event",
        symbol="000001.SZ",
        sleeve="MAIN",
        causal_industry="TEST",
        signal_date=pd.Timestamp("2019-01-31"),
        signal_cal_idx=100,
        invalid_step_cum=2.0,
    )


def execution_row(cal_idx: int, *, open_: float = 10.0, high: float = 10.0) -> dict:
    return {
        "trade_date": pd.Timestamp("2019-01-31") + pd.offsets.BDay(cal_idx - 100),
        "cal_idx": cal_idx,
        "open": open_,
        "high": high,
        "coord_open": open_,
        "coord_high": high,
        "invalid_step_cum": 2.0,
        "coordinate_factor": 1.0,
        "trade_status": 1,
        "current_day_data_tradable": True,
        "current_valid": True,
        "market_rule_valid": True,
        "corporate_action_count": 0,
        "corporate_action_valid": True,
        "corporate_action_blocking": False,
        "hard_valid": True,
        "up_limit_price": 11.0,
        "down_limit_price": 9.0,
        "available_at": pd.Timestamp("2019-01-31 15:00:00"),
        "decision_at": pd.Timestamp("2019-01-31 15:00:00"),
    }


def test_stage_b_never_enters_on_the_signal_bar() -> None:
    path = pd.DataFrame(
        [execution_row(100, high=12.0), execution_row(101), execution_row(102, high=11.0)]
    )
    result = stage_b.EXECUTION.replay_one(execution_candidate(), path)
    assert result["status"] == "COMPLETED"
    assert result["entry_cal_idx"] == 101
    assert result["exit_cal_idx"] == 102


def test_fallback_open_precedes_same_day_high() -> None:
    path = pd.DataFrame([execution_row(101), execution_row(122, open_=9.5, high=12.0)])
    result = stage_b.EXECUTION.replay_one(execution_candidate(), path)
    assert result["status"] == "COMPLETED"
    assert result["exit_reason"] == "H20_TIME_STOP"
    assert result["exit_price"] == 9.5
