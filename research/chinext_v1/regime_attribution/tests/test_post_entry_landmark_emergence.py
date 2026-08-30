from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run_post_entry_landmark_emergence as landmark


def test_day5_is_the_only_primary_landmark() -> None:
    assert "return_5d" not in landmark.BASE_CONTROLS
    assert landmark.OUTPUT_TABLE.name == "post_entry_landmark_attribution.csv"


def test_later_landmarks_are_fixed_and_not_imputed() -> None:
    assert landmark.SECONDARY_ENDPOINTS == (
        "winner20",
        "false_breakout",
        "severe_loss",
        "mfe",
        "round_trip_return",
    )
