from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts/build_phase1_conversion_panel.py"
)
SPEC = spec_from_file_location("conversion_panel", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_terminal_classes_are_mutually_exclusive_at_boundaries() -> None:
    cases = {
        0.50: "EXTREME_WINNER",
        0.20: "RIGHT_TAIL_WINNER",
        0.0200001: "ORDINARY_WINNER",
        0.02: "FLAT",
        -0.02: "FLAT",
        -0.0200001: "SMALL_LOSER",
        -0.099999: "SMALL_LOSER",
        -0.10: "SEVERE_LOSER",
    }
    assert {value: MODULE.terminal_class(value) for value in cases} == cases


def test_path_descriptors_preserve_signs_and_no_clipping() -> None:
    path = [
        {"close_return": 0.00, "low_return": -0.01},
        {"close_return": 0.10, "low_return": -0.02},
        {"close_return": 0.20, "low_return": 0.05},
        {"close_return": 0.05, "low_return": 0.00},
    ]
    result = MODULE.path_descriptors(path, days_to_mfe=2, terminal_return=0.05)
    assert result["pre_mfe_mae"] == -0.02
    assert result["pre_peak_direction_efficiency"] == 1.0
    assert result["pre_peak_positive_day_fraction"] == 1.0
    assert result["post_peak_positive_day_fraction"] == 0.0
    assert result["days_from_peak_to_exit"] == 1
    assert result["post_peak_close_giveback"] == pytest.approx(0.15)
    assert result["post_peak_decay_rate"] == pytest.approx(0.15)
