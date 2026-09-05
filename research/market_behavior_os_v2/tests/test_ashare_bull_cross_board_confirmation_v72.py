from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd

RUNNER = (
    Path(__file__).resolve().parents[1]
    / "scripts/run_ashare_bull_cross_board_confirmation_v72.py"
)
sys.path.insert(0, str(RUNNER.parent))
SPEC = importlib.util.spec_from_file_location("v72_runner", RUNNER)
assert SPEC and SPEC.loader
v72 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(v72)


def source_rows() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "event_id": ["a", "b", "c", "d"],
            "source_event_id": ["va", "vb", "vc", "vd"],
            "signal_date": pd.to_datetime(
                ["2020-01-02", "2020-01-02", "2020-01-03", "2020-01-03"]
            ),
            "decision_at": pd.to_datetime(
                [
                    "2020-01-02 15:00",
                    "2020-01-02 15:00",
                    "2020-01-03 15:00",
                    "2020-01-03 15:00",
                ]
            ),
            "available_at": pd.to_datetime(
                [
                    "2020-01-02 15:00",
                    "2020-01-02 15:00",
                    "2020-01-03 15:00",
                    "2020-01-03 15:00",
                ]
            ),
            "feature_latest_timestamp": pd.to_datetime(
                [
                    "2020-01-02 15:00",
                    "2020-01-02 15:00",
                    "2020-01-03 15:00",
                    "2020-01-03 15:00",
                ]
            ),
            "sleeve": ["MAIN", "CHINEXT", "MAIN", "MAIN"],
            "causal_industry": ["i1", "i2", "i1", "i2"],
            "hard_valid": [True, True, True, True],
        }
    )


def test_cross_board_gate_uses_same_completed_close() -> None:
    state = v72.attach_cross_board_state(source_rows())
    by_date = state.groupby("signal_date").cross_board_confirmation.first().to_dict()
    assert by_date[pd.Timestamp("2020-01-02")]
    assert not by_date[pd.Timestamp("2020-01-03")]
    assert not state.cross_board_state_known_at.gt(state.decision_at).any()


def test_selection_retains_only_cross_board_date_and_preserves_parent_identity() -> None:
    selected = v72.select_candidates(source_rows())
    assert selected.event_id.tolist() == ["V72|a", "V72|b"]
    assert selected.source_event_id.tolist() == ["a", "b"]
    assert selected.same_day_v65_main_count.tolist() == [1, 1]
    assert selected.same_day_v65_chinext_count.tolist() == [1, 1]


def test_outcome_remap_changes_only_event_identity() -> None:
    selected = v72.select_candidates(source_rows())
    outcomes = pd.DataFrame(
        {
            "event_id": ["a", "b", "c", "d"],
            "status": ["COMPLETED"] * 4,
            "net_return": [0.01, 0.02, 0.03, 0.04],
        }
    )
    mapped = v72.remap_outcomes(outcomes, selected)
    assert mapped.event_id.tolist() == ["V72|a", "V72|b"]
    assert mapped.source_outcome_event_id.tolist() == ["a", "b"]
    assert mapped.net_return.tolist() == [0.01, 0.02]
